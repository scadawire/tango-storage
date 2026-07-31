import time
from tango import AttrQuality, AttrWriteType, DispLevel, DevState, Attr, CmdArgType, UserDefaultAttrProp
from tango.server import Device, attribute, command, DeviceMeta
from tango.server import class_property, device_property
from tango.server import run
import os
import json
from json import JSONDecodeError
import sys,time,datetime,traceback,os

class Storage(Device, metaclass=DeviceMeta):

    STATE_FILE = "storage_state.json"
    init_dynamic_attributes = device_property(dtype=str, default_value="")
    dynamicAttributes = {}
    dynamicAttributeValueTypes = {}


    def init_device(self):
        self.set_state(DevState.INIT)
        self.get_device_properties(self.get_device_class())

        if self.init_dynamic_attributes != "":
            try:
                attributes = json.loads(self.init_dynamic_attributes)
                for attributeData in attributes:
                    self.add_dynamic_attribute(attributeData["name"], 
                        attributeData.get("data_type", ""), attributeData.get("min_value", ""), attributeData.get("max_value", ""),
                        attributeData.get("unit", ""), attributeData.get("write_type", ""), attributeData.get("label", ""),
                        attributeData.get("modifier", ""), attributeData.get("min_alarm", ""), attributeData.get("max_alarm", ""),
                        attributeData.get("min_warning", ""), attributeData.get("max_warning", ""))
            except JSONDecodeError as e:
                attributes = self.init_dynamic_attributes.split(",")
                for attribute in attributes:
                    self.info_stream("Init dynamic attribute: %s", str(attribute.strip()))
                    self.add_dynamic_attribute(attribute.strip())
        self.load_state()
        self.set_state(DevState.ON)

    def add_dynamic_attribute(self, topic,
            variable_type_name="DevString", min_value="", max_value="",
            unit="", write_type_name="", label="", modifier="",
            min_alarm="", max_alarm="", min_warning="", max_warning=""):
        self.info_stream("Adding dynamic attribute: %s", topic)
        if topic == "": return
        prop = UserDefaultAttrProp()
        variableType = self.stringValueToVarType(variable_type_name)
        writeType = self.stringValueToWriteType(write_type_name)
        self.dynamicAttributeValueTypes[topic] = variableType
        if(min_value != "" and min_value != max_value): prop.set_min_value(min_value)
        if(max_value != "" and min_value != max_value): prop.set_max_value(max_value)
        if(unit != ""): prop.set_unit(unit)
        if(label != ""): prop.set_label(label)
        if(min_alarm != ""): prop.set_min_alarm(min_alarm)
        if(max_alarm != ""): prop.set_max_alarm(max_alarm)
        if(min_warning != ""): prop.set_min_warning(min_warning)
        if(max_warning != ""): prop.set_max_warning(max_warning)
        attr = Attr(topic, variableType, writeType)
        attr.set_default_properties(prop)
        self.add_attribute(attr, r_meth=self.read_dynamic_attr, w_meth=self.write_dynamic_attr)
        self.dynamicAttributes[topic] = ""
        self.set_change_event(topic, True, False)

    def stringValueToVarType(self, variable_type_name) -> CmdArgType:
        if(variable_type_name == "DevBoolean"):
            return CmdArgType.DevBoolean
        if(variable_type_name == "DevLong"):
            return CmdArgType.DevLong
        if(variable_type_name == "DevDouble"):
            return CmdArgType.DevDouble
        if(variable_type_name == "DevFloat"):
            return CmdArgType.DevFloat
        if(variable_type_name == "DevString"):
            return CmdArgType.DevString
        if(variable_type_name == ""):
            return CmdArgType.DevString
        raise Exception("given variable_type '" + variable_type_name + "' unsupported, supported are: DevBoolean, DevLong, DevDouble, DevFloat, DevString")

    def stringValueToWriteType(self, write_type_name) -> AttrWriteType:
        # READ_WITH_WRITE is not offered: tango only accepts it for an attribute that names an
        # associated write attribute, which no driver here defines. Building the Attr anyway does
        # not fail just that attribute, it aborts init_device with "Associated attribute not
        # defined" and takes the whole device server down.
        if(write_type_name == "READ"):
            return AttrWriteType.READ
        if(write_type_name == "WRITE"):
            return AttrWriteType.WRITE
        if(write_type_name == "READ_WRITE"):
            return AttrWriteType.READ_WRITE
        if(write_type_name == ""):
            return AttrWriteType.READ_WRITE
        raise Exception("given write_type '" + write_type_name + "' unsupported, supported are: READ, WRITE, READ_WRITE")

    def stringValueToTypeValue(self, name, val):
        if(self.dynamicAttributeValueTypes[name] == CmdArgType.DevBoolean):
            if(str(val).lower() == "false"):
                return False
            if(str(val).lower() == "true"):
                return True
            return bool(int(self.stringValueToFloat(val)))
        if(self.dynamicAttributeValueTypes[name] == CmdArgType.DevLong):
            return int(self.stringValueToFloat(val))
        if(self.dynamicAttributeValueTypes[name] == CmdArgType.DevDouble):
            return self.stringValueToFloat(val)
        if(self.dynamicAttributeValueTypes[name] == CmdArgType.DevFloat):
            return self.stringValueToFloat(val)
        return val

    # an attribute that was never written holds no text yet, and reading it has to answer a value of its
    # type rather than end in a conversion error: a client only sees the read fail, not why. That is what
    # kept the lqr controller of demo026 from regulating - it reads its actor attribute before it writes
    # it for the first time, and never got past that read.
    def stringValueToFloat(self, val):
        return float(val) if val not in ('', None) else 0.0

    def read_dynamic_attr(self, attr):
        name = attr.get_name()
        value = self.dynamicAttributes[name]
        self.debug_stream("read value %s: %s", name, value)
        attr.set_value(self.stringValueToTypeValue(name, value))

    def write_dynamic_attr(self, attr):
        value = str(attr.get_write_value())
        name = attr.get_name()
        self.debug_stream("write value %s: %s", name, value)
        self.dynamicAttributes[name] = value
        self.save_state()
        self.push_change_event(name, self.stringValueToTypeValue(name, value))

    def save_state(self):
        state = {
            "values": self.dynamicAttributes,
        }
        with open(self.STATE_FILE, "w") as f:
            json.dump(state, f)

    def load_state(self):
        if not os.path.exists(self.STATE_FILE):
            return
        try:
            with open(self.STATE_FILE) as f:
                state = json.load(f)
                self.dynamicAttributes = state.get("values", {})
        except (OSError, JSONDecodeError):
            pass

if __name__ == "__main__":
    deviceServerName = os.getenv("DEVICE_SERVER_NAME")
    run({deviceServerName: Storage})
