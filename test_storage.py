"""
Unit test for Storage -- an in-memory attribute store with JSON persistence.

Storage has no protocol at all: writes land in the dynamicAttributes cache (and a
JSON state file) and reads serve them back, coercing to the attribute's declared
Tango type. The tests drive the real Storage methods as unbound functions against
a lightweight State stub whose __getattr__ falls through to the class, and a
MockAttr standing in for a Tango attribute, following the other drivers' pattern.

Usage:
    python test_storage.py
"""

import sys
import os
import functools
import tempfile
import json
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tango import CmdArgType, AttrWriteType

from Storage import Storage


# ===========================================================================
#  Mock Tango attribute
# ===========================================================================

class MockAttr:
    def __init__(self, name, write_value=None):
        self._name = name
        self._write_value = write_value
        self.value = None

    def get_name(self):
        return self._name

    def get_write_value(self):
        return self._write_value

    def set_value(self, value):
        self.value = value


# ===========================================================================
#  State carrier -- method lookups fall through to Storage
# ===========================================================================

class State:
    def __init__(self):
        self.dynamicAttributes = {}
        self.dynamicAttributeValueTypes = {}

        fd, path = tempfile.mkstemp(prefix="storage_state_", suffix=".json")
        os.close(fd)
        os.remove(path)
        self.STATE_FILE = path

        self.events = []   # (name, value) from push_change_event
        self.logs = []

    def _log(self, level, msg, *args):
        self.logs.append((level, msg % args if args else msg))

    def debug_stream(self, msg, *a): self._log("DEBUG", msg, *a)
    def info_stream(self, msg, *a):  self._log("INFO", msg, *a)
    def warn_stream(self, msg, *a):  self._log("WARN", msg, *a)
    def error_stream(self, msg, *a): self._log("ERROR", msg, *a)

    def push_change_event(self, name, value):
        self.events.append((name, value))

    def __getattr__(self, name):
        attr = getattr(Storage, name, None)
        if callable(attr):
            return functools.partial(attr, self)
        if attr is not None:
            return attr
        raise AttributeError("'State' has no attribute '%s'" % name)

    def cleanup(self):
        if os.path.exists(self.STATE_FILE):
            os.remove(self.STATE_FILE)


def register(s, name, var_type_name):
    """Register an attribute the way add_dynamic_attribute would, minus the Tango bits."""
    s.dynamicAttributeValueTypes[name] = Storage.stringValueToVarType(s, var_type_name)
    s.dynamicAttributes[name] = ""


def write(s, name, value):
    Storage.write_dynamic_attr(s, MockAttr(name, value))


def read(s, name):
    attr = MockAttr(name)
    Storage.read_dynamic_attr(s, attr)
    return attr.value


# ===========================================================================
#  Test harness
# ===========================================================================

passed = 0
failed = 0
errors = []


def assert_equal(name, actual, expected, tolerance=None):
    global passed, failed
    ok = abs(actual - expected) <= tolerance if tolerance is not None else actual == expected
    if ok:
        passed += 1
        print("  PASS  %s" % name)
    else:
        failed += 1
        msg = "  FAIL  %s: expected %r, got %r" % (name, expected, actual)
        print(msg)
        errors.append(msg)


def assert_true(name, value):  assert_equal(name, bool(value), True)
def assert_false(name, value): assert_equal(name, bool(value), False)


def assert_raises(name, fn):
    global passed, failed
    try:
        fn()
    except Exception:
        passed += 1
        print("  PASS  %s" % name)
        return
    failed += 1
    msg = "  FAIL  %s: expected an exception, none raised" % name
    print(msg)
    errors.append(msg)


# ===========================================================================
#  Type mappers
# ===========================================================================

def test_string_value_to_var_type():
    print("\n-- stringValueToVarType --")
    s = State()
    assert_equal("DevBoolean", Storage.stringValueToVarType(s, "DevBoolean"), CmdArgType.DevBoolean)
    assert_equal("DevLong", Storage.stringValueToVarType(s, "DevLong"), CmdArgType.DevLong)
    assert_equal("DevDouble", Storage.stringValueToVarType(s, "DevDouble"), CmdArgType.DevDouble)
    assert_equal("DevFloat", Storage.stringValueToVarType(s, "DevFloat"), CmdArgType.DevFloat)
    assert_equal("DevString", Storage.stringValueToVarType(s, "DevString"), CmdArgType.DevString)
    assert_equal("empty defaults to DevString", Storage.stringValueToVarType(s, ""), CmdArgType.DevString)
    # regression: the raise used to reference an undefined `variable_type` (NameError);
    # it must now raise a clean, informative Exception naming the bad type.
    assert_raises("unsupported type raises cleanly",
                  lambda: Storage.stringValueToVarType(s, "DevNope"))
    s.cleanup()


def test_string_value_to_write_type():
    print("\n-- stringValueToWriteType --")
    s = State()
    assert_equal("READ", Storage.stringValueToWriteType(s, "READ"), AttrWriteType.READ)
    assert_equal("WRITE", Storage.stringValueToWriteType(s, "WRITE"), AttrWriteType.WRITE)
    assert_equal("READ_WRITE", Storage.stringValueToWriteType(s, "READ_WRITE"), AttrWriteType.READ_WRITE)
    assert_equal("READ_WITH_WRITE", Storage.stringValueToWriteType(s, "READ_WITH_WRITE"), AttrWriteType.READ_WITH_WRITE)
    assert_equal("empty defaults to READ_WRITE", Storage.stringValueToWriteType(s, ""), AttrWriteType.READ_WRITE)
    assert_raises("unsupported write type raises",
                  lambda: Storage.stringValueToWriteType(s, "SOMETHING"))
    s.cleanup()


def test_string_value_to_type_value():
    print("\n-- stringValueToTypeValue coercion --")
    s = State()
    register(s, "b", "DevBoolean")
    assert_true("bool 'True'", Storage.stringValueToTypeValue(s, "b", "True"))
    assert_false("bool 'false'", Storage.stringValueToTypeValue(s, "b", "false"))
    assert_true("bool '1'", Storage.stringValueToTypeValue(s, "b", "1"))
    assert_false("bool '0'", Storage.stringValueToTypeValue(s, "b", "0"))

    register(s, "l", "DevLong")
    assert_equal("long '42'", Storage.stringValueToTypeValue(s, "l", "42"), 42)
    assert_equal("long '3.9' truncates", Storage.stringValueToTypeValue(s, "l", "3.9"), 3)

    register(s, "d", "DevDouble")
    assert_equal("double '3.14'", Storage.stringValueToTypeValue(s, "d", "3.14"), 3.14, tolerance=1e-9)

    register(s, "st", "DevString")
    assert_equal("string passthrough", Storage.stringValueToTypeValue(s, "st", "hello"), "hello")
    s.cleanup()


# ===========================================================================
#  Read / write funnel round-trips
# ===========================================================================

def test_roundtrip_each_type():
    print("\n-- write/read round-trip per type --")
    s = State()

    register(s, "flag", "DevBoolean")
    write(s, "flag", True)
    assert_true("boolean True round-trip", read(s, "flag"))
    write(s, "flag", False)
    assert_false("boolean False round-trip", read(s, "flag"))

    register(s, "count", "DevLong")
    write(s, "count", 12345)
    assert_equal("long round-trip", read(s, "count"), 12345)

    register(s, "temp", "DevDouble")
    write(s, "temp", -2.5)
    assert_equal("double round-trip", read(s, "temp"), -2.5, tolerance=1e-9)

    register(s, "name", "DevString")
    write(s, "name", "scada")
    assert_equal("string round-trip", read(s, "name"), "scada")
    s.cleanup()


def test_write_pushes_typed_event():
    print("\n-- write pushes a typed change event --")
    s = State()
    register(s, "count", "DevLong")
    write(s, "count", 7)
    assert_equal("one event pushed", len(s.events), 1)
    name, value = s.events[0]
    assert_equal("event name", name, "count")
    assert_equal("event value is typed (int, not str)", value, 7)
    assert_true("event value is int", isinstance(value, int))
    s.cleanup()


def test_read_serves_cached_value():
    print("\n-- read serves the cache without a device --")
    s = State()
    register(s, "name", "DevString")
    s.dynamicAttributes["name"] = "preset"   # value placed directly in the cache
    assert_equal("reads cached value", read(s, "name"), "preset")
    s.cleanup()


# ===========================================================================
#  State persistence
# ===========================================================================

def test_save_and_load_state():
    print("\n-- save_state / load_state round-trip --")
    s = State()
    register(s, "a", "DevLong")
    register(s, "b", "DevString")
    write(s, "a", 99)
    write(s, "b", "text")

    assert_true("state file created", os.path.exists(s.STATE_FILE))
    with open(s.STATE_FILE) as f:
        raw = json.load(f)
    assert_equal("values persisted under 'values'", raw["values"]["a"], "99")

    # a fresh instance pointed at the same file restores the cache
    s2 = State()
    s2.STATE_FILE = s.STATE_FILE
    s2.dynamicAttributeValueTypes = {"a": CmdArgType.DevLong, "b": CmdArgType.DevString}
    Storage.load_state(s2)
    assert_equal("cache restored", s2.dynamicAttributes["a"], "99")
    assert_equal("typed read after restore", read(s2, "a"), 99)
    s.cleanup()


def test_load_state_missing_file():
    print("\n-- load_state: missing file is a no-op --")
    s = State()
    s.STATE_FILE = s.STATE_FILE + ".does-not-exist"
    Storage.load_state(s)  # must not raise
    assert_equal("cache stays empty", len(s.dynamicAttributes), 0)


def test_load_state_corrupt_file():
    print("\n-- load_state: corrupt JSON is swallowed --")
    s = State()
    with open(s.STATE_FILE, "w") as f:
        f.write("{not valid json")
    Storage.load_state(s)  # OSError/JSONDecodeError are caught
    assert_equal("cache unchanged on corrupt file", len(s.dynamicAttributes), 0)
    s.cleanup()


# ===========================================================================
#  Main
# ===========================================================================

def main():
    global failed
    print("=" * 60)
    print("  Storage Unit Test")
    print("=" * 60)
    try:
        test_string_value_to_var_type()
        test_string_value_to_write_type()
        test_string_value_to_type_value()
        test_roundtrip_each_type()
        test_write_pushes_typed_event()
        test_read_serves_cached_value()
        test_save_and_load_state()
        test_load_state_missing_file()
        test_load_state_corrupt_file()
    except Exception:
        traceback.print_exc()
        failed += 1

    total = passed + failed
    print("\n%s" % ("=" * 60))
    print("  Results: %d/%d passed, %d failed" % (passed, total, failed))
    if errors:
        print("\n  Failures:")
        for e in errors:
            print("    %s" % e)
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
