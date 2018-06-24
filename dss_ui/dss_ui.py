# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2018, Galen Curwen-McAdams

import random
import io
import functools
import subprocess
import operator
import hashlib
import os
import shutil
import roman
import atexit
import argparse
from functools import lru_cache
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.config import Config
from kivy.graphics.vertex_instructions import Rectangle
from kivy.graphics import Color, Line, Ellipse, InstructionGroup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scatter import Scatter
from kivy.uix.scatterlayout import ScatterLayout
from kivy.uix.label import Label
from kivy.core.text import Label as CoreLabel
from kivy.uix.button import Button
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.popup import Popup
from kivy.uix.dropdown import DropDown
from kivy.clock import Clock
from kivy.uix.textinput import TextInput
from kivy.uix.accordion import Accordion, AccordionItem
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.graphics.texture import Texture
from PIL import Image as PImage
from lxml import etree
import redis
import attr
import uuid
import colour
from ma_cli import data_models
from ma_wip import visualizations
from lings import ruling, pipeling

r_ip, r_port = data_models.service_connection()
binary_r = redis.StrictRedis(host=r_ip, port=r_port)
redis_conn = redis.StrictRedis(host=r_ip, port=r_port, decode_responses=True)

Config.read('config.ini')

kv = """
#:import ScrollEffect  kivy.effects.scroll.ScrollEffect
<ScatterTextWidget>:
    id:image_container
    orientation: 'vertical'
    image_grid:image_grid
    scroller:scroller
    ScrollViewer:
        size_hint_y: None
        size_hint_x:None
        canvas:
            Color:
                rgba: 1, 0, 0, 0.05
            Rectangle:
                pos: self.pos
                size: self.size
        id:scroller
        width:self.parent.width
        height:self.parent.height
        effect_cls:ScrollEffect
        GridLayout:
            canvas:
                Color:
                    rgba: 0, 0, 0, 0.5
                Rectangle:
                    pos: self.pos
                    size: self.size
            id: image_grid
            rows: 1
            size_hint_y: None
            size_hint_x: None
            #size:self.parent.size
            #width:3000
            spacing: 0, 0
            padding: 0, 0
<GlworbRecycleView>:
    viewclass: 'GlworbLabel'
    RecycleBoxLayout:
        default_size: None, None
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height
        orientation: 'vertical'
<GlworbLabel>:
    size: self.texture_size
"""

Builder.load_string(kv)


@attr.s
class Rule(object):
    source_field = attr.ib(default="")
    comparator_symbol = attr.ib(default="")
    comparator_params = attr.ib(default=attr.Factory(list))
    dest_field = attr.ib(default="")
    rule_result = attr.ib(default="")
    rough_amount = attr.ib(default=0)

    def quote(self, string):
        if string:
            if not string.startswith('"'):
                string = '"' + string
            if not string.endswith('"'):
                string += '"'
            return string
        else:
            return '""'
    @property
    def rule_result_string(self):
        quoted_rule_result = self.rule_result
        return self.quote(quoted_rule_result)

    @property
    def comparator_params_string(self):
        params = self.comparator_params
        if self.comparator_symbol == "~~":
            params[0] = self.quote(params[0])
        return " ".join(params)

    @property
    def as_string(self):
        s = attr.asdict(self)
        s.update({'comparator_params_string' : self.comparator_params_string})
        s.update({'rule_result_string' : self.rule_result_string})
        return "{source_field} {comparator_symbol} {comparator_params_string} -> {dest_field} {rule_result_string}".format(**s)

@attr.s
class RuleSet(object):
    rules = attr.ib(default=attr.Factory(list))

    @property
    def as_string(self):
        return ""

@attr.s
class RuleSymbols(object):
    symbols = {
    "~~" : "case insensitive equals",
    "is" : "is of type",
    "between" : "integer range between"
    }

    types = ["int", "roman", "str"]

    # symbol_params
    # is <type>
    # between int1,int2

@attr.s
class Group(object):
    regions = attr.ib(default=attr.Factory(list))
    color = attr.ib(default=None)
    name = attr.ib(default="")
    hide = attr.ib(default=False)
    source_dimensions = attr.ib(default=attr.Factory(list))
    source = attr.ib(default="")

    @color.validator
    def check(self, attribute, value):
        if value is None:
            setattr(self,'color', colour.Color(pick_for=self))

    @property
    def x(self):
        return self.region_rectangle()[0]

    @property
    def x2(self):
        return self.region_rectangle()[2]

    @property
    def y(self):
        return self.region_rectangle()[1]

    @property
    def y2(self):
        return self.region_rectangle()[3]

    @property
    def width(self):
        return self.x2 - self.x

    @property
    def height(self):
        return self.y2 - self.y
    
    @property
    def scaled_bounding_rectangle(self):
        # scaled to fullsize with offsets removed
        # and coordinates shifted to upper left 0,0
        # Problem: final y axis of rectangle is a little off
        try:
            rect = self.region_rectangle()
            ox = self.display_offset_x
            oy = self.display_offset_y
            # remove offsets
            print("offsets x, y", self.display_offset_x, self.display_offset_y)
            rect = [rect[0] - ox, rect[1], rect[2] - ox, rect[3]]
            # get xy scaling
            x_scale = self.source_width / self.source_dimensions[0]
            y_scale = self.source_height / self.source_dimensions[1]
            x = rect[0]
            y = rect[1]
            x2 = rect[2]
            y2 = rect[3]
            # kivy canvas 0,0 is lower left corner
            # image processing expects 0,0 is upper left corner
            x = int(round(x * x_scale))
            y = int(round(y * y_scale))
            x2 = int(round(x2 * x_scale))
            y2 = int(round(y2 * y_scale))
            # subtract height to go from bottom left 0,0
            # used by kivy canvas to top left 0,0 used by
            # pillow, x does not need adjustment
            h = abs(y2 - y)
            y -= self.source_height
            y2 -= self.source_height
            y = abs(y)
            y2 = abs(y2)
            # get width and height to print xywh
            # use with 'ma-cli image' rectangle command
            # to debug coordinates
            w = abs(x2 - x)
            h = abs(y2 - y)
            print("scaled rect:", x,y,x2,y2)
            print("scaled xywh:", x, y, w, h)
            return [x, y, x2, y2]
        except TypeError:
            return None

    @property
    def scaled_width(self):
        pass

    @property
    def scaled_height(self):
        pass

    @property
    def bounding_rectangle(self):
        #x y w h
        rect = self.region_rectangle()
        try:
            rect[2] = rect[2] - rect[0]
            rect[3] = rect[3] - rect[1]
            return rect
        except TypeError:
            return None

    def bounding_contains_point(self, x, y):
        contains_x = False
        contains_y = False
        rect = self.region_rectangle()
        try:
            if rect[0] < x < rect[2]:
                contains_x = True

            if rect[1] < y <rect[3]:
                contains_y = True
        except TypeError:
            pass

        if contains_x and contains_y:
            return True
        else:
            return False

    def region_rectangle(self):
        """Return bounding rectangle of
        all regions"""
        min_x = None
        min_y = None
        max_x = None
        max_y = None

        for region in self.regions:
            if min_x is None or region[0] < min_x:
                min_x = region[0]

            if min_y is None or region[1] < min_y:
                min_y = region[1]

            if max_x is None or region[2] > max_x:
                max_x = region[2]

            if max_y is None or region[3] > max_y:
                max_y = region[3]

        return [min_x, min_y, max_x, max_y]

@attr.s
class Category(object):
    color = attr.ib(default=None)
    name = attr.ib(default=None)
    rough_amount = attr.ib(default=0)
    rough_amount_start = attr.ib(default=None)
    rough_amount_end = attr.ib(default=None)
    # rough_order could be negative float
    rough_order = attr.ib(default=None)
    # set name to random uuid if none supplied
    @name.validator
    def check(self, attribute, value):
        if value is None:
            setattr(self,'name',str(uuid.uuid4()))

class ClickableFileChooserListView(FileChooserListView):
    def __init__(self, app, **kwargs):
        self.app = app
        super(ClickableFileChooserListView, self).__init__(**kwargs)

    def on_submit(self, *args):
        try:
            clicked_file = args[0][0]
            clicked_file_path = os.path.dirname(clicked_file)
            if clicked_file.endswith(".jpg"):
                img = self.app.file_binary(clicked_file)
                self.app.thumbs_info.add_thumb(img)
                self.app.thumbnails.add_widget(img, index=len(self.app.thumbnails.children))
            elif clicked_file.endswith(".xml"):
                xml = etree.parse(clicked_file)
                for record in xml.xpath('//group'):
                    #<region x="500" y="300" x2="600" y2="400" width="100" height="100" source="20d5fba1ae631fe3358ea57571be781dc971a7420597b55f15cffa46c79fea2d"/>
                    name = str(record.xpath("./@name")[0])
                    color = str(record.xpath("./@color")[0])
                    width = int(float(record.xpath("./@width")[0]))
                    height = int(float(record.xpath("./@height")[0]))
                    for region in record.getchildren():
                        x = int(region.xpath("./@x")[0])
                        y = int(region.xpath("./@y")[0])
                        x2 = int(region.xpath("./@x2")[0])
                        y2 = int(region.xpath("./@y2")[0])
                        source = region.xpath("./@source")[0]
                        img = self.app.file_binary(os.path.join(clicked_file_path, "{}.jpg".format(source)))
                        self.app.thumbs_info.add_thumb(img)
                        self.app.thumbnails.add_widget(img, index=len(self.app.thumbnails.children))
                        # load rectangle selections
                        group = Group()
                        group.name = name
                        group.color = colour.Color(color)
                        group.source_dimensions = [width, height]
                        group.source = source
                        group.regions.append([x, y, x2, y2])
                        self.app.working_image.group_container.add_group(group)
                        self.app.working_image.group_container.update_group(group.name)
                        if group not in self.app.groups:
                            self.app.groups.append(group)
                        self.app.working_image.draw_groups()
        except IndexError as ex:
            print(ex)
            pass

class GlworbLabel(RecycleDataViewBehavior, ButtonBehavior, Label):
    def __init__(self, **kwargs):
        super(GlworbLabel, self).__init__(**kwargs)

    def on_press(self):
        self.parent.parent.app.add_glworb(self.glworb)

class GlworbRecycleView(RecycleView):
    def __init__(self, **kwargs):
        self.viewclass = 'GlworbLabel'

        super(GlworbRecycleView, self).__init__(**kwargs)
        self.populate()

    def populate(self):
        self.data = []
        for glworb in data_models.enumerate_data(pattern="glworb:*"):
            self.data.append({'text': str(data_models.pretty_format(redis_conn.hgetall(glworb), glworb)), 'glworb' : glworb, 'fields' : redis_conn.hgetall(glworb)})

    def filter_view(self, filter_text):
        if filter_text:
            self.data = []
            for glworb in data_models.enumerate_data(pattern="glworb:*"):
                glworb_text = str(data_models.pretty_format(redis_conn.hgetall(glworb), glworb))
                if filter_text in glworb_text:
                    self.data.append({'text': glworb_text, 'glworb' : glworb, 'fields' : redis_conn.hgetall(glworb)})
        else:
            self.populate()

    def mass_add(self, sort_by=None):
        if sort_by is None:
            sorted_glworbs = sorted(self.data)
        else:
            sorted_glworbs = sorted(self.data, key=lambda x: (x['fields'][sort_by]))

        for glworb in sorted_glworbs:
            self.app.add_glworb(glworb['glworb'])

class ScatterTextWidget(BoxLayout):

    def __init__(self, **kwargs):
        super(ScatterTextWidget, self).__init__(**kwargs)
        self.image_grid.bind(minimum_height=self.image_grid.setter('height'),
                             minimum_width=self.image_grid.setter('width'))

    def on_touch_up(self, touch):
        return super(ScatterTextWidget, self).on_touch_up(touch)

class ScrollViewer(ScrollView):
    def __init__(self, **kwargs):
        super(ScrollViewer, self).__init__(**kwargs)

    def handle_keybinds(self, keycode, modifiers):
        if keycode[1] == 'left' and not modifiers:
            try:
                self.scroll_x -= (1/len(self.parent.image_grid.children))
                if self.scroll_x < 0:
                    self.scroll_x = 0
            except TypeError as ex:
                pass
        elif keycode[1] == 'right' and not modifiers:
            try:
                self.scroll_x += (1/len(self.parent.image_grid.children))
                if self.scroll_x > 1:
                    self.scroll_x = 1
            except TypeError as ex:
                pass

    def enlarge(self, zoom_amount=2):
        for child in self.parent.image_grid.children:
            child.width *= zoom_amount
            child.height *= zoom_amount

    def shrink(self, zoom_amount=2):
        for child in self.parent.image_grid.children:
            print(child.size)
            child.width /= zoom_amount
            child.height /= zoom_amount

    def on_touch_down(self, touch):
        #self.dispatch('on_test_event', touch)  # Some event that happens with on_touch_down
        #zoom_amount = 100
        zoom_amount = 2
        if touch.button == 'left':
            return super().on_touch_down(touch)
        elif touch.button == 'scrollup':
            self.enlarge()
        elif touch.button == 'scrolldown':
            self.shrink()

        return super(ScrollViewer, self).on_touch_down(touch)

class GlworbInfoCell(ButtonBehavior, TextInput):
    def __init__(self, container, **kwargs):
        self.container = container
        #important that ButtonBehavior is before TextInput
        super(GlworbInfoCell, self).__init__(**kwargs)

    def on_touch_up(self, touch):

        if touch.button == 'right':
            self.container.set_key(self)
        return super().on_touch_up(touch)

class GlworbInfo(BoxLayout):
    def __init__(self, app, **kwargs):
        self.app = app
        self.current_uuid = None
        self.env_binary_key = None
        self.scroll_container = ScrollView(bar_width=20, size_hint_y=1)
        self.glworb_container = BoxLayout(orientation='vertical', size_hint_y=None, height=800, minimum_height=200)
        super(GlworbInfo, self).__init__(**kwargs)
        self.scroll_container.add_widget(self.glworb_container)
        self.add_widget(self.scroll_container)

    def update_current(self):
        if self.current_uuid:
            self.update(self.current_uuid)

    def update(self, uuid):
        self.current_uuid = uuid
        container = self.glworb_container
        container.clear_widgets()
        fields = redis_conn.hgetall(uuid)
        for k, v in sorted(fields.items()):
            row = BoxLayout(orientation='horizontal', size_hint_y=.1)
            field = GlworbInfoCell(container=self, text=k, multiline=False)
            # use prior_field to delete correct field
            # even if field text has changed
            field.prior_field = field.text
            row.add_widget(field)
            # select the binary field to be passed in the env dictionary
            # for the pipes
            #field.bind(on_press=lambda widget:  self.set_key(widget))
            # remove field:value if field set to ''
            field.bind(on_text_validate=lambda widget: self.update_field(widget))

            if field.text == self.env_binary_key:
                field.background_color = (0, 0, 1, 1)
            if v in [category.category.name for category in self.app.categories]:
                category = [category.category for category in self.app.categories if v == category.category.name][0]
                field_value = TextInput(text=v, background_color=(*category.color.rgb,1), multiline=False)
                row.add_widget(field_value)
                field_value.field = field
                field_value.bind(on_text_validate=lambda widget: self.update_field_value(widget.field.text, widget.text))
            else:
                field_value = TextInput(text=v, multiline=False)
                row.add_widget(field_value)
                field_value.field = field
                field_value.bind(on_text_validate=lambda widget: self.update_field_value(widget.field.text, widget.text))
            container.add_widget(row)
        container.add_widget(Label(text="add field:value", halign="left", size_hint_y=None, size_hint_x=None, height=44))
        new_field_name = TextInput(text="", multiline=False)
        new_field_value = TextInput(text="", multiline=False)
        new_field_name.bind(on_text_validate=lambda widget: self.add_field(widget, new_field_value))
        new_field_value.bind(on_text_validate=lambda widget: self.add_field(new_field_name, widget))
        add_row = BoxLayout(orientation='horizontal', size_hint_y=.1)

        add_row.add_widget(new_field_name)
        add_row.add_widget(new_field_value)
        container.add_widget(add_row)
        container.add_widget(Label(text="pipe env -> {}".format(str(self.app.pipe_env)), size_hint_y=None, height=44))

    def add_field(self, name_widget, value_widget):
        if name_widget.text == "":
            # name must not be empty
            # turn textfield background red to indicate
            name_widget.background_color = (1, 0, 0, 1)
        else:
            name_widget.background_color = (1, 1, 1, 1)
            self.update_field_value(name_widget.text,value_widget.text)
            name_widget.text = ""
            value_widget.text = ""
            self.update(self.current_uuid)

    def update_field(self, widget):
        field = widget.text
        prior_field = widget.prior_field
        if field == "":
            print("removing field {}".format(widget.prior_field))
            # remove field if emptied
            print(data_models.remove_field(widget.prior_field, [self.current_uuid]))
            self.update(self.current_uuid)
        else:
            value=''
            for row in self.glworb_container.children:
                for w in row.children:
                    try:
                        if w.field == widget:
                            value = w.text
                            break
                    except Exception as ex:
                        print(ex)
            print("value is {}".format(value))
            data_models.add_field(field, [self.current_uuid], values=[value])
            self.update(self.current_uuid)

    def update_field_value(self, field, value):
        # add_field will also overwrite existing field
        print(field, [self.current_uuid], [value])
        data_models.add_field(field, [self.current_uuid], values=[value])
        self.update(self.current_uuid)

    def add_field_value(self, field, value):
        data_models.add_field(field, [self.current_uuid], values=[value])
        self.update(self.current_uuid)

    def set_key(self, widget):
        self.env_binary_key = widget.text
        widget.background_color = (0, 0, 1, 1)
        self.app.pipe_env['key'] = widget.text
        self.update(self.current_uuid)

class RuleGenerator(BoxLayout):
    def __init__(self, app, **kwargs):
        self.orientation='vertical'
        self.app = app
        self.rule_symbols = RuleSymbols()
        super(RuleGenerator, self).__init__(**kwargs)
        self.create_container = BoxLayout()
        self.action_container = BoxLayout()

        self.source_fields = DropDown()
        source_default = Button(text="", size_hint_y=None, height=44)
        source_default.bind(on_press=self.update)
        source_default.bind(on_release=self.source_fields.open)
        self.source_default = source_default
        self.source_fields.bind(on_select=lambda instance, x: setattr(source_default, 'text', x))

        self.comparator_symbols =  DropDown()
        for symbol in self.rule_symbols.symbols.keys():
            btn = Button(text=symbol, size_hint_y=None, height=44)
            btn.bind(on_release=lambda btn: self.comparator_symbols.select(btn.text))
            self.comparator_symbols.add_widget(btn)

        comparator_default = Button(text="", size_hint_y=None, height=44)
        comparator_default.bind(on_release=self.comparator_symbols.open)
        self.comparator_default = comparator_default
        self.comparator_symbols.bind(on_select=lambda instance, x: self.comparator_params(instance, x))


        # this should somehow be modular / extensible
        # and defined by RuleSymbols class
        param_container = BoxLayout(orientation='horizontal')
        self.param_container = param_container

        self.case_insensitive_equals_params = DropDownInput(size_hint_y=None, height=44)
        self.type_params =  DropDown()
        self.type_params_default = Button(text="", size_hint_y=None, height=44)
        for t in self.rule_symbols.types:
            btn = Button(text=t, size_hint_y=None, height=44)
            btn.bind(on_release=lambda btn: self.type_params.select(btn.text))
            self.type_params.add_widget(btn)
        self.type_params_default.bind(on_release=self.type_params.open)
        self.type_params.bind(on_select=lambda instance, x: setattr(self.type_params_default, 'text', x))

        self.between_params_default = BoxLayout(orientation='horizontal')
        self.between_params_default.add_widget(TextInput(text="", size_hint_y=None, height=44))
        self.between_params_default.add_widget(Label(text="to", size_hint_y=None, height=44))
        self.between_params_default.add_widget(TextInput(text="", size_hint_y=None, height=44))

        self.dest_fields = DropDownInput(size_hint_y=None, height=44)
        self.rule_result = DropDownInput(preload=self.app.categories, preload_attr="category.name", size_hint_y=None, height=44)

        self.add_widget(self.create_container)
        self.add_widget(self.action_container)

        create_button = Button(text="create rule", size_hint_y=None, height=44)
        create_button.bind(on_release=self.create_rule)
        self.action_container.add_widget(create_button)

        self.create_container.add_widget(Label(text="result", font_size=15, size_hint_y=None, height=44))
        self.create_container.add_widget(self.rule_result)
        self.create_container.add_widget(Label(text="is a", font_size=15, size_hint_y=None, height=44))
        self.create_container.add_widget(self.dest_fields)
        self.create_container.add_widget(Label(text="if region", font_size=15, size_hint_y=None, height=44, text_size=(self.width, None)))
        self.create_container.add_widget(source_default)
        self.create_container.add_widget(Label(text="has characteristics", font_size=15, size_hint_y=None, height=44, text_size=(self.width, None)))
        self.create_container.add_widget(comparator_default)
        self.create_container.add_widget(param_container)

    def create_rule(self, widget):
        rule = Rule()
        rule.source_field = self.source_default.text
        rule.comparator_symbol = self.comparator_default.text
        params = []

        for c in self.param_container.children:
            if hasattr(c, "text"):
                params.append(c.text)
            # search one layer deep for additional params
            try:
                for cc in c.children:
                    if hasattr(cc, "text") and not isinstance(cc, Label):
                        params.append(cc.text)
            except Exception as ex:
                pass

        rule.comparator_params = params
        rule.dest_field = self.dest_fields.text
        rule.rule_result = self.rule_result.text

        # create rule for immediate visualization
        # of rule applicability
        r = etree.Element("rule")
        r.set("source", rule.source_field)
        r.set("destination", rule.dest_field)
        r.set("result", rule.rule_result)
        for param in rule.comparator_params:
            p = etree.SubElement(r, "parameter")
            p.set("symbol", rule.comparator_symbol)
            p.set("values",str(param))
        # for now, use ruling from lings
        # would be nice not to have lings as
        # dependency for ui
        rule_dsl = ruling.rule_xml2str(etree.tostring(r).decode())
        ruling.add_rule(rule_dsl, expire=1000)
        # if using regions from image, need to
        # create pipe(s) too...
        created_pipes = set()
        if rule.source_field in [group.name for group in self.app.groups]:
            group = [group for group in self.app.groups if group.name == rule.source_field][0]
            x, y, x2, y2 = group.scaled_bounding_rectangle
            w = abs(x2 - x)
            h = abs(y2 - y)
            pipe = {}
            pipe["group_name"] = group.name
            pipe["x"] = x
            # Problem: subtracted amount is an arbitrary, used until
            # y axis issues are resolved...
            # see scaled_bounding_rectangle
            magic_y = 150
            pipe["y"] = y - magic_y
            pipe["w"] = w
            pipe["h"] = h
            pipe["key_name"] = rule.source_field
            # 'p' prefix since textx metamodel ID must start with aA-zZ
            pipe["pipe_name"] = "p" + hashlib.sha224("{x}{y}{w}{h}".format(**pipe).encode()).hexdigest()
            # img_ocr_rectangle stalls out the zerorpc connection
            #pipe_string = "pipe {pipe_name} {{ img_ocr_rectangle {key_name} {x} {y} {w} {h}\n}}".format(**pipe)
            pipe_string = "pipe {pipe_name} {{ img_crop_to_key {x} {y} {w} {h} {group_name}_rule_test_binary\n img_ocr_key {group_name}_rule_test_binary {key_name}\n}}".format(**pipe)
            print("created: " + pipe["pipe_name"])
            print(pipe_string)
            pipeling.add_pipe(pipe_string, expire=1000)
            created_pipes.add(pipe["pipe_name"])
        # use raw kwarg to get only rule names
        all_rules = ruling.get_rules(raw=True)
        # run all thumbnail images through pipe
        # multiple regions = multiple ocr_rectangles
        # single pipe or multiple pipes?
        for thumb in self.app.thumbnails.children:
            # if source_path is None:
            # save to bytesio and add as glworb
            if thumb.source_path:
                for pipe_name in created_pipes:
                    print(pipe_name, thumb.source_path)
                    try:
                        # {"key" : "binary_key"}
                        pipeling.pipe(pipe_name, thumb.source_path, env=self.app.pipe_env)
                    except AttributeError as ex:
                        print(ex)
                try:
                    for rule_name in all_rules:
                        print(rule_name, thumb.source_path)
                        ruling.rule(rule_name, thumb.source_path)
                except Exception as ex:
                    print(ex)
        print(etree.tostring(r, pretty_print=True).decode())

        self.rule_container.add_rule(RuleItem(rule))

    def comparator_params(self, widget, selected_value, *args):
        self.comparator_default.text = selected_value
        print(self.param_container.children)
        for c in self.param_container.children:
            self.param_container.remove_widget(c)

        if selected_value == "is":
            try:
                self.param_container.add_widget(self.type_params_default)
            except Exception as ex:
                pass
        elif selected_value == 'between':
            try:
                self.param_container.add_widget(self.between_params_default)
            except Exception as ex:
                pass
        elif selected_value == '~~':
            try:
                self.param_container.add_widget(self.case_insensitive_equals_params)
            except Exception as ex:
                pass

    def update(self, widget, *args):
        # clear all dropdown items on update to remove deleted
        self.source_fields.children[0].children = []
        for group in self.app.groups:
            btn = Button(text=group.name, size_hint_y=None, height=44, color=group.color.rgb)
            btn.bind(on_release=lambda btn: self.source_fields.select(btn.text))

            if group.name not in [ c.text for c in self.source_fields.children[0].children if hasattr(c, 'text')]:
                self.source_fields.add_widget(btn)

class OutputPreview(BoxLayout):
    def __init__(self, app, **kwargs):
        self.app = app
        self.orientation = "vertical"
        self.output_path = "/tmp"
        self.path_input = TextInput(text=self.output_path, size_hint_y=None, height=44, multiline=False, font_size=20)
        self.path_input.bind(on_text_validate=lambda instance: setattr(self, 'output_path', instance.text))
        self.output_preview = TextInput(text="", multiline=True)
        self.output_status = TextInput(text="", multiline=True)
        #self.path_input.bind(on_text_validate=functools.partial(self.on_text_enter))
        self.export_types = {'xml' : "generated.xml",
                             'xml->pub' : "project:<project-name>",
                             'xml+sources(dir)': "generated",
                             'xml+sources(zipped)': "generated.zip"}
        self.export_options =  DropDown()
        self.export_options_selected = Button(text="xml", size_hint_y=None, height=44)
        for t in self.export_types.keys():
            btn = Button(text=t, size_hint_y=None, height=44)
            btn.bind(on_release=self.update_export_options)
            self.export_options.add_widget(btn)
        self.export_options_selected.bind(on_release=self.export_options.open)
        self.export_options.bind(on_select=lambda instance, x: setattr(self.export_options_selected, 'text', x))
        self.export_button = Button(text="export", size_hint_y=None, height=44)
        self.export_button.bind(on_release=lambda instance: self.generate_xml(write_output=True, output_type=self.export_options_selected.text))
        self.export_container = BoxLayout(orientation="horizontal")
        self.export_container.add_widget(self.export_button)
        self.export_container.add_widget(self.path_input)
        self.export_container.add_widget(self.export_options_selected)

        super(OutputPreview, self).__init__(**kwargs)
        self.add_widget(self.export_container)
        self.add_widget(self.output_preview)
        self.add_widget(self.output_status)

    def on_touch_down(self, touch):
        self.generate_xml()
        return super(OutputPreview, self).on_touch_down(touch)

    def update_export_options(self, widget):
        self.export_options.select(widget.text)
        dest =  self.export_types[widget.text]
        self.output_status.text += os.path.join(self.output_path, dest) + "\n"

    def generate_xml(self, write_output=False, output_filename=None, output_type=None, output_path=None, generate_preview=True):
        # clear existing
        self.output_preview.text = ""
        if output_path is None:
            output_path = self.output_path

        if output_filename is None:
            output_filename = "generated.xml"

        if output_type is None:
            output_type = "xml"
        # possible outputs
        # xml (root <project></project>)
        # xml (root <machine></machine>)
        # xml + images used in groups (dir/zip)
        # xml -> gsl -> scripts to start/stop pipes/rules
        #     machinic tooling supports much of that... 
        # xml -> gsl -> scripts to set based on project attributes
        #     for example setting zoom based on height/width
        # xml -> gsl? -> queuing for projects based on attributes
        #     for example grouping by various aspects
        #     stop previous project pipe / rules, start new project...
        machine = etree.Element("machine")

        p = etree.Element("project")
        for k, v in self.app.project.items():
            if not isinstance(v, dict):
                p.set(k, str(v))
        # self.text += etree.tostring(p, pretty_print=True).decode()
        machine.append(p)

        # session specific things such as working image
        # loaded thumbnails, etc...
        # this xml can be used to load previous session
        # and ignored by other programs
        s = etree.Element("session")
        if self.app.session['working_image']:
            s.set("working_image", self.app.session['working_image'])
        # set will not be ordered
        # t = etree.Element("thumbs")
        for thumb in self.app.session['working_thumbs']:
            if thumb:
                s.append(etree.Element("thumb", source_path=thumb))
        # s.append(t)
        machine.append(s)

        used_source_hashes = set()
        # groups
        for group in self.app.groups:
            g = etree.Element("group",name=group.name)
            sequence = etree.Element("sequence",name=group.name)
            g.set("name", group.name)
            g.set("color", group.color.hex_l)
            for dimension_name, dimension in zip(['width','height','depth'], group.source_dimensions):
                g.set(dimension_name, str(dimension))
            for region in group.regions:
                r = etree.SubElement(g, "region")
                x = str(region[0])
                y = str(region[1])
                x2 = str(region[2])
                y2 = str(region[3])
                width = str(region[2] - region[0])
                height = str(region[3] - region[1])
                r.set("x", x)
                r.set("y", y)
                r.set("x2", x2)
                r.set("y2", y2)
                r.set("width", width)
                r.set("height", height)
                if group.source:
                    r.set("source", group.source)
                    used_source_hashes.add(group.source)
                else:
                    r.set("source", "")
                g.append(r)

                # sequences for pipes
                step = etree.Element("step",call="crop_to_key")
                for arg, descrip in zip([x, y, width, height, group.name], ["x", "y", "width", "height", "to key"]):
                    argument = etree.Element("argument", value=str(arg), description=descrip)
                    step.append(argument)
                sequence.append(step)

            machine.append(g)
            machine.append(sequence)

        # rules
        for rule in self.app.rule_container.rules:
            r = etree.Element("rule")
            r.set("source", rule.source_field)
            r.set("destination", rule.dest_field)
            r.set("result", rule.rule_result)
            for param in rule.comparator_params:
                p = etree.SubElement(r, "parameter")
                p.set("symbol", rule.comparator_symbol)
                p.set("values",str(param))
            # self.text += etree.tostring(r, pretty_print=True).decode()
            machine.append(r)
            #self.text += rule.as_string + "\n"

        # categories
        #self.app.categories is currently a list of CategoryItems
        for category in self.app.categories:
            category = category.category
            c = etree.Element("category")
            c.set("name", category.name)
            c.set("color", category.color.hex_l)
            c.set("rough_amount", str(category.rough_amount))
            try:
                c.set("rough_amount_start", str(category.rough_amount_start))
                c.set("rough_amount_end", str(category.rough_amount_end))
            except Exception as ex:
                pass
            c.set("rough_order", str(category.rough_order))
            # self.text += etree.tostring(c, pretty_print=True).decode()
            machine.append(c)

        if generate_preview is True:
            self.output_preview.text += etree.tostring(machine, pretty_print=True).decode()
        # project dimensions width height depth
        if write_output is True:
            machine_root = etree.ElementTree(machine)
            xml_filename = output_filename
            if not os.path.isdir(output_path):
                os.mkdir(output_path)

            if os.path.isfile(os.path.join(output_path, output_filename)):
                os.remove(os.path.join(output_path, output_filename))

            if output_type == "xml":
                machine_root.write(os.path.join(output_path, xml_filename), pretty_print=True)
            elif output_type == "xml->pub":
                key_name = "project:{}".format(self.app.project['name'])
                redis_conn.set(key_name, etree.tostring(machine_root.getroot(), encoding='utf8', method='xml'))
                #redis_conn.publish(key_name)
            elif output_type == "xml+sources(dir)":
                machine_root.write(os.path.join(output_path, xml_filename), pretty_print=True)
                for h in used_source_hashes:
                    export_source(self.app.thumbnails.children, h, path=output_path)
            elif output_type == "xml+sources(zipped)":
                # create a temp directory for material to zip
                zip_path = "/tmp/generated"
                if not os.path.isdir(zip_path):
                    os.mkdir(zip_path)
                machine_root.write(os.path.join(zip_path, xml_filename), pretty_print=True)
                for h in used_source_hashes:
                    export_source(self.app.thumbnails.children, h, path=zip_path)

                #.zip extension will be appended by function
                shutil.make_archive(os.path.join(output_path, 'generated'), 'zip', zip_path)

def export_source(images, source_hash, path=None):
    if path is None:
        path = ""

    for img in images:
        try:
            if source_hash == img.source_hash:
                file = os.path.join(path, '{}.jpg'.format(source_hash))
                img.texture.save(file,flipped=False)
        except Exception as ex:
            print(ex)
            pass

    # for sources from redis:
    # contents = binary_r.get(uuid)
    # file = io.BytesIO()
    # file = io.BytesIO(contents)
    # file.seek(0)
    # filehash = hashlib.new('sha256')
    # filehash.update(file.getvalue())
    # export_to = os.path.join(path, filehash.hexdigest())
    # print(export_to)
    # with open(export_to, 'wb') as f:
    #     shutil.copyfileobj(export_to, f)

class DropDownInput(TextInput):

    def __init__(self, preload=None, preload_attr=None, preload_clean=True, **kwargs):
        self.multiline = False
        self.drop_down = DropDown()
        self.drop_down.bind(on_select=self.on_select)
        self.bind(on_text_validate=self.add_text)
        self.preload = preload
        self.preload_attr = preload_attr
        self.preload_clean = preload_clean
        self.not_preloaded = set()
        super(DropDownInput, self).__init__(**kwargs)
        self.add_widget(self.drop_down)

    def add_text(self,*args):
        if args[0].text not in [btn.text for btn in self.drop_down.children[0].children if hasattr(btn ,'text')]:
            btn = Button(text=args[0].text, size_hint_y=None, height=44)
            self.drop_down.add_widget(btn)
            btn.bind(on_release=lambda btn: self.drop_down.select(btn.text))
            if not 'preload' in args:
                self.not_preloaded.add(btn)

    def on_select(self, *args):
        self.text = args[1]
        if args[1] not in [btn.text for btn in self.drop_down.children[0].children if hasattr(btn ,'text')]:
            self.drop_down.append(Button(text=args[1]))
            self.not_preloaded.add(btn)

    def on_touch_down(self, touch):
        preloaded = set()
        if self.preload:
            for thing in self.preload:
                if self.preload_attr:
                    # use operator to allow dot access of attributes
                    thing_string = str(operator.attrgetter(self.preload_attr)(thing))
                else:
                    thing_string = str(thing)
                self.add_text(Button(text=thing_string),'preload')
                preloaded.add(thing_string)

        # preload_clean removes entries that
        # are not in the preload source anymore
        if self.preload_clean is True:
            added_through_widget = [btn.text for btn in self.not_preloaded if hasattr(btn ,'text')]
            for btn in self.drop_down.children[0].children:
                try:
                    if btn.text not in preloaded and btn.text not in added_through_widget:
                        self.drop_down.remove_widget(btn)
                except Exception as ex:
                    pass

        return super(DropDownInput, self).on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current == self:
            self.drop_down.open(self)
        return super(DropDownInput, self).on_touch_up(touch)


class RuleItem(BoxLayout):
    def __init__(self, rule, **kwargs):
        self.rule = rule
        # self.rough_items_input = TextInput(hint_text=str(rule.rough_amount), size_hint_x=.1, multiline=False, height=44, size_hint_y=None)
        # self.rough_items_input.bind(on_text_validate=self.update)
        # add colorpicker for palette
        self.rule_string = Label(text=self.rule.as_string)
        self.rule_remove = Button(text= "del", size_hint_x=.2, font_size=20, height=44, size_hint_y=None)
        self.rule_remove.bind(on_press=self.remove_rule)

        super(RuleItem, self).__init__(**kwargs)
        # self.add_widget(self.rough_items_input)
        self.add_widget(self.rule_string)
        self.add_widget(self.rule_remove)

    def update(self,widget):
        self.rule.rough_amount = int(widget.text)
        self.parent.update_project()

    def remove_rule(self, widget):
        # call RuleContainer
        self.parent.remove_rule(self)

class RuleContainer(BoxLayout):
    def __init__(self, **kwargs):
        super(RuleContainer, self).__init__(**kwargs)

    def add_rule(self, rule):
        rule.height = 44
        rule.size_hint_y = None
        self.add_widget(rule)
        self.parent.scroll_to(rule)

    def remove_rule(self, rule_id):
        for rule in self.children:
            try:
                if rule == rule_id:
                    del rule.rule
                    self.remove_widget(rule)
            except AttributeError as ex:
                pass

    @property
    def rules(self):
        return [rule.rule for rule in self.children if hasattr(rule, 'rule')]

class CategoryItem(BoxLayout):
    def __init__(self, category, **kwargs):
        self.category = category
        super(CategoryItem, self).__init__(**kwargs)
        # loaded categories may already have a color
        if category.color is None:
            category.color = colour.Color(pick_for=category)
        self.category_color = self.category.color.rgb
        category_color_button = Button(text= "", background_normal='', font_size=20)
        category_color_button.bind(on_press=self.pick_color)
        category_color_button.background_color = (*self.category_color, 1)

        # rough order: floats, positive or negative
        self.rough_order_input = TextInput(text=str(category.rough_order), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)
        self.rough_order_input.bind(on_text_validate=self.update_order)

        category_name = TextInput(text=self.category.name, multiline=False, font_size=20, background_color=(.6, .6, .6, 1))
        category_name.bind(on_text_validate=functools.partial(self.on_text_enter))
        category_remove = Button(text= "del", font_size=20)
        category_remove.bind(on_press=self.remove_category)
        self.rough_items_input = TextInput(text=str(category.rough_amount), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)
        self.rough_items_input.bind(on_text_validate=self.update_direct)

        # start/end should accept roman numerals too
        # show as text if int or roman numeral, otherwise
        # show as hint_text
        if self.is_int(category.rough_amount_start) or self.is_roman(category.rough_amount_start):
            self.rough_items_start_input = TextInput(text=str(category.rough_amount_start), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)
        else:
            self.rough_items_start_input = TextInput(hint_text=str(category.rough_amount_start), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)

        self.rough_items_start_input.bind(on_text_validate=self.update_range)

        if self.is_int(category.rough_amount_end) or self.is_roman(category.rough_amount_end):
            self.rough_items_end_input = TextInput(text=str(category.rough_amount_end), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)
        else:
            self.rough_items_end_input = TextInput(hint_text=str(category.rough_amount_end), size_hint_x=.2, multiline=False, height=44, size_hint_y=None)

        self.rough_items_end_input.bind(on_text_validate=self.update_range)

        self.add_widget(category_color_button)
        self.add_widget(self.rough_order_input)
        self.add_widget(category_name)
        self.add_widget(self.rough_items_input)
        self.add_widget(self.rough_items_start_input)
        self.add_widget(self.rough_items_end_input)
        self.add_widget(category_remove)
        self.category_color_button = category_color_button
        self.update_range(self.rough_items_end_input)

    def is_int(self, value):
        try:
            int(value)
            return True
        except:
            return False

    def is_roman(self, value):
        try:
            roman.fromRoman(value.upper())
            return True
        except:
            return False

    def remove_category(self, *args):
        self.parent.remove_category(self.category.name)

    def update_range(self, widget):
        # entering enormous values will cause a
        # stall that is unexplained by ui as the
        # overview images update
        value_range = [self.rough_items_start_input.text, self.rough_items_end_input.text]

        for i, value in enumerate(value_range):
            try:
                value_range[i] = int(value)
            except Exception as ex:
                try:
                    # must be uppercase for roman module
                    value_range[i] = roman.fromRoman(value.upper())
                except Exception as ex:
                    pass

        try:
            rough_range = value_range[1] - value_range[0]
            # turn range backgrounds green to show
            # that range computation is used
            self.rough_items_end_input.background_color = (0, 1, 0, 1)
            self.rough_items_start_input.background_color = (0, 1, 0, 1)
            self.rough_items_input.text = str(rough_range)
            self.category.rough_amount_start = self.rough_items_start_input.text
            self.category.rough_amount_end = self.rough_items_end_input.text

            self.update(self.rough_items_input)
        except Exception as ex:
            self.rough_items_end_input.background_color = (1, 0, 0, 1)
            self.rough_items_start_input.background_color = (1, 0, 0, 1)

    def update_direct(self, widget):
        # turn range backgrounds gray to show
        # that range input ignored
        self.rough_items_end_input.background_color = (.6, .6, .6, 1)
        self.rough_items_start_input.background_color = (.6, .6, .6, 1)
        self.update(widget)

    def update_order(self, widget):
        try:
            self.category.rough_order = float(widget.text)
            self.parent.reorder_widgets()
            self.parent.update()
        except Exception as ex:
            pass

    def update(self,widget):
        self.category.rough_amount = int(widget.text)
        # during initial run to set amount colors
        # widget may not have parent
        try:
            self.parent.update()
        except AttributeError:
            pass

    def pick_color(self,*args):
        color_picker = ColorPickerPopup()
        color_picker.content.bind(color=self.on_color)
        color_picker.open()

    def on_color(self, instance, *args):
        self.category.color.rgb = instance.color[:3]
        self.category_color_button.background_color = (*self.category.color.rgb, 1)
        #update thumbnail preview
        self.parent.update()

    def on_text_enter(self, instance, *args):
        print(instance.text, args)
        old_name = self.category.name
        self.category.name = instance.text
        self.parent.updated_category_name(old_name, self.category.name)
        try:
            if self.category.name in self.parent.app.defaults['category']:
                self.category.color = colour.Color(self.parent.app.defaults['category'][self.category.name])
                self.category_color_button.background_color = (*self.category.color.rgb, 1)
                self.parent.update()
        except Exception as ex:
            pass

class CategoryContainer(BoxLayout):
    def __init__(self, **kwargs):
        self.categories = set()
        self.app = None
        super(CategoryContainer, self).__init__(**kwargs)

    def updated_category_name(self, old_name, new_name):
        try:
            del self.app.project['categories'][old_name]
            del self.app.project['palette'][old_name]
        except Exception as ex:
            pass
        self.update()

    def update(self):
        if 'categories' not in self.app.project:
            self.app.project['categories'] = {}
        if 'palette' not in self.app.project:
            self.app.project['palette'] = {}
        if 'order' not in self.app.project:
            self.app.project['order'] = {}

        for c in self.children:
            if c.category.name not in self.app.project['categories']:
                self.app.project['categories'][c.category.name] = 0

            if c.category.name not in self.app.project['palette']:
                self.app.project['palette'][c.category.name] = {}

            if c.category.name not in self.app.project['order']:
                self.app.project['order'][c.category.name] = 0

            self.app.project['categories'][c.category.name] = c.category.rough_amount
            self.app.project['order'][c.category.name] = c.category.rough_order

            # colour rgb produces r g bvalues between 0 - 1
            # pillow uses rgb ints 0 -255 instead of floats
            # so pass hex value and let visualize.py convert
            self.app.project['palette'][c.category.name]['fill'] = c.category.color.hex_l

        self.app.update_project_image()
        self.app.update_project_thumbnail()

    def add_category(self, category):
        if category.rough_order is None:
            category.rough_order = float(len(self.children))
        c = CategoryItem(category, height=50, size_hint_y=None)
        self.add_widget(c, int(category.rough_order))

        self.categories.add(c)
        self.parent.scroll_to(c)
        self.reorder_widgets()

    def reorder_widgets(self):
        b = self.children.copy()
        self.clear_widgets()
        b.sort(key=lambda widget: widget.category.rough_order)
        print(b)
        for d in b:
            self.add_widget(d, int(d.category.rough_order))

    def remove_category(self, name):
        for category in self.children:
            try:
                if category.category.name == name:
                    try:
                        del self.app.project['categories'][category.category.name]
                        del self.app.project['palette'][category.category.name]
                        self.app.update_project_image()
                        self.app.update_project_thumbnail()
                    except Exception as ex:
                        pass
                    del category.category
                    self.remove_widget(category)
                    self.categories.remove(category)
            except AttributeError as ex:
                pass

    # @property
    # def categories(self):
    #     return [category.category for category in self.children if hasattr(category, 'category')]

class CategoryGenerator(BoxLayout):
    def __init__(self,**kwargs):
        super(CategoryGenerator, self).__init__(**kwargs)
        create_button = Button(text="create category", size_hint_y=None, height=44)
        create_button.bind(on_release=self.create_category)
        self.add_widget(create_button)

    def create_category(self, widget):
        category = Category()
        self.category_container.add_category(category)

class GroupItem(BoxLayout):
    def __init__(self,**kwargs):
        self.group = None
        self.initial_update = False
        super(GroupItem, self).__init__(**kwargs)

    def update_group_display(self):
        if self.initial_update:
            self.group_region.text = str(self.group.scaled_bounding_rectangle)
            self.group_color.color = self.group.color.rgb
            self.group_color.background_color = background_color=(*self.group.color.rgb, 1)
        else:
            group_color = Button(text= "@@@", background_normal='', font_size=20, color=self.group.color.rgb, background_color=(*self.group.color.rgb, 1))
            group_color.bind(on_press=self.pick_color)
            group_name = TextInput(text=self.group.name, multiline=False, font_size=20, background_color=(.6, .6, .6, 1))
            group_region = Label(text=str(self.group.bounding_rectangle))
            group_name.bind(on_text_validate=functools.partial(self.on_text_enter))
            group_hide = Button(text="hide", font_size=20)
            group_hide.bind(on_press=self.hide_group)
            group_redraw = Button(text="redraw", font_size=20)
            group_redraw.bind(on_press=self.redraw_region)
            group_remove = Button(text= "del", font_size=20)
            group_remove.bind(on_press=self.remove_group)

            self.add_widget(group_color)
            self.add_widget(group_name)
            self.add_widget(group_region)
            self.add_widget(group_hide)
            self.add_widget(group_redraw)
            self.add_widget(group_remove)

            self.group_region = group_region
            self.group_color = group_color
            self.initial_update = True

    def hide_group(self, button, *args):
        hide_status = {True: 'unhide',
                       False: 'hide'}
        self.group.hide = not self.group.hide
        button.text = hide_status[self.group.hide]
        self.parent.request_redraw()

    def redraw_region(self, *args):
        # ClickableImage canvas into redraw mode
        # first click x,y
        # second click x2, y2
        self.parent.group_region_redraw(self)

    def remove_group(self, *args):
        self.parent.remove_group(self.group.name)

    def pick_color(self,*args):
        color_picker = ColorPickerPopup()
        color_picker.content.bind(color=self.on_color)
        color_picker.open()

    def on_color(self, instance, *args):
        self.group.color.rgb = instance.color[:3]
        self.update_group_display()
        self.parent.request_redraw()

    def on_text_enter(self, instance, *args):
        print(instance.text, args)
        # add old name to removed_groups to
        # allow canvas to remove associated draws
        self.parent.app.removed_groups.append(self.group.name)
        self.group.name = instance.text
        try:
            if self.group.name in self.parent.app.defaults['group']:
                self.group.color = colour.Color(self.parent.app.defaults['group'][self.group.name])
                self.update_group_display()
        except Exception as ex:
            pass
        self.parent.request_redraw()


class ClickableLabel(ButtonBehavior, Label):
    def __init__(self, **kwargs):
        super(ClickableLabel, self).__init__(**kwargs)

class ThumbItem(BoxLayout):
    def __init__(self, thumb, **kwargs):
        self.thumb = thumb
        self.orientation = "horizontal"
        super(ThumbItem, self).__init__(**kwargs)
        thumb_label = ClickableLabel(text=self.thumb.source_hash)
        thumb_label.bind(on_press=lambda widget: self.select())
        thumb_remove = Button(text="del", font_size=20)
        thumb_remove.bind(on_press=lambda widget: self.parent.remove_thumb(self))
        self.add_widget(thumb_label)
        self.thumb_label = thumb_label
        self.add_widget(thumb_remove)

    def select(self):
        self.parent.select_thumb(self)

class ThumbContainer(BoxLayout):
    def __init__(self, app, **kwargs):
        self.app = app
        self.highlight_color = [0, 1, 0, 1]
        self.default_color = [1, 1, 1, 1]
        super(ThumbContainer, self).__init__(**kwargs)

    def add_thumb(self, thumb):
        thumb_widget = ThumbItem(thumb, size_hint_y=None, height=44)
        self.add_widget(thumb_widget)
        self.parent.scroll_to(thumb_widget)

    def remove_thumb(self, thumb_item):
        self.app.remove_from_thumbs(thumb_item.thumb.source_hash)
        self.remove_widget(thumb_item)

    def select_thumb(self, thumb_item):
        self.app.change_from_thumb(thumb_item.thumb)
        self.highlight(thumb_item)

    def center_on(self, thumb):
        for child in self.children:
            if child.thumb == thumb:
                self.parent.scroll_to(child)
                thumb.highlight(self.highlight_color)
                self.highlight(child)
                break

    def highlight(self, thumb_item):
        # unhighlight all labels before
        # highlighting selected thumb
        for child in self.children:
            try:
                child.thumb_label.color = self.default_color
            except AttributeError as ex:
                pass
        thumb_item.thumb_label.color = self.highlight_color


class GroupContainer(BoxLayout):
    def __init__(self, **kwargs):
        super(GroupContainer, self).__init__(**kwargs)

    def update_group(self, name):
        for group in self.children:
            try:
                if group.group.name == name:
                    group.update_group_display()
            except AttributeError:
                pass

    def add_group(self, group):
        g = GroupItem(height=50, size_hint_y=None)
        g.group = group
        g.update_group_display()
        self.add_widget(g)
        # set scroll location to created group
        self.parent.scroll_to(g)

    def remove_group(self, name):
        for group in self.children:
            try:
                if group.group.name == name:
                    self.app.groups.remove(group.group)
                    self.app.removed_groups.append(name)
                    del group.group
                    self.remove_widget(group)
                    self.request_redraw()
            except AttributeError as ex:
                pass

    def group_region_redraw(self, group):
        self.app.working_image.select_region(group)

    def request_redraw(self):
        self.app.working_image.redraw()

class OverlayImage(Image):
    def __init__(self, app, **kwargs):
        self.app = app
        super(OverlayImage, self).__init__(**kwargs)
        self.draw_groups()

    def draw_groups(self):
        with self.canvas:
            for group in self.app.groups + self.app.removed_groups:
                # this will not clear removed groups
                try:
                    self.canvas.remove_group(group.name)
                    # Color(128, 128, 128, 0.5)
                    Color(*group.color.rgb, 0.5)
                    try:
                        for x, y, w, h in [group.bounding_rectangle]:
                            if not group.hide:
                                Rectangle(pos=(x,y), size=(w, h), group=group.name)
                                Line(rectangle=(0 + group.display_offset_x, 0 + group.display_offset_y, group.source_dimensions[0], group.source_dimensions[1]), width=3, group=group.name)
                            else:
                                Line(rectangle=(x, y, w, h), width=3, group=group.name)
                    except Exception as ex:
                        # None may be returned if no regions in group
                        pass
                except AttributeError:
                    self.canvas.remove_group(group)

        self.app.removed_groups = []

class ClickableImage(Image):
    def __init__(self, source_hash=None, source_path=None, **kwargs):
        self.rows = 0
        self.cols = 0
        self.row_spacing = 100
        self.col_spacing = 100
        self.offset_x = 0
        self.offset_y = 0
        self.geometry = []
        self.app = None
        self.resized = False
        self.source_hash = source_hash
        self.source_path = source_path
        self.hidden = False
        self.hidden_hash = None
        self.selection_mode = False
        self.selection_mode_selections = []
        self.selection_mode_group = None
        super(ClickableImage, self).__init__(**kwargs)

    def unhighlight(self):
        highlight_group = "highlight"
        with self.canvas:
            self.canvas.remove_group(highlight_group)

    def highlight(self, highlight_color=None):
        highlight_group = "highlight"
        for child in self.parent.children:
            try:
                child.unhighlight()
            except AttributeError as ex:
                pass
        if highlight_color is None:
            highlight_color = [0, 1, 0, 1]

        with self.canvas:
            self.canvas.remove_group(highlight_group)
            w, h = self.size
            x, y = self.pos
            Color(*highlight_color)
            Line(rectangle=(x, y, w, h), width=3, group=highlight_group)

    def resize_window(self, *args):
        # only resize once...
        if self.resized is False:
            # w, h = self.norm_image_size
            # w = int(w)
            # h = int(h)
            # Window.size = w * 2, h
            self.resized = True

    def redraw(self):
        self.geometry = []
        self.clear_grid()
        self.draw_groups()
        self.draw_grid()

    def select_region(self, group):
        self.clear_grid()
        self.selection_mode = True
        self.selection_mode_selections = []
        self.selection_mode_group = group

    def clear_grid(self):
        self.canvas.remove_group('selections')
        self.canvas.remove_group('clicks')

    @lru_cache(maxsize=32)
    def hidden_texture(self, width, height):
        texture = Texture.create(size=self.texture_size, colorfmt="rgb")
        size = self.texture_size[0] * self.texture_size[1] * 3
        buf = ([bytes(int(x * 255 / size) for x in range(size))])
        buf = b''.join(buf)
        texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
        return texture

    def hide(self):
        # clicking a thumb may have changed image texture
        # if has changed, reset hidden status so that toggling
        # works as expected
        if self.hidden_hash != self.source_hash:
            self.hidden = False
        self.hidden = not self.hidden
        if self.hidden:
            self.texture = self.hidden_texture(*self.norm_image_size)
            self.hidden_hash = self.source_hash
        else:
            # retrieve texture from thumbs
            for thumb in self.app.thumbnails.children:
                if thumb.source_hash == self.source_hash:
                    self.texture = thumb.texture
                    try:
                        self.source_path = thumb.source_path
                    except AttributeError:
                        pass
                    self.source_hash = thumb.source_hash

    def draw_groups(self):
        with self.canvas:
            for group in self.app.groups + self.app.removed_groups:
                # this will not clear removed groups
                try:
                    self.canvas.remove_group(group.name)
                    # Color(128, 128, 128, 0.5)
                    Color(*group.color.rgb, 0.5)
                    try:
                        for x, y, w, h in [group.bounding_rectangle]:
                            if not group.hide:
                                Rectangle(pos=(x,y), size=(w, h), group=group.name)
                                # try to draw source dimension rectangle
                                try:
                                    Line(rectangle=(0 + group.display_offset_x, 0 + group.display_offset_y, group.source_dimensions[0], group.source_dimensions[1]), width=3, group=group.name)
                                except:
                                    pass
                            else:
                                Line(rectangle=(x, y, w, h), width=3, group=group.name)
                            caption = CoreLabel(text=group.name, font_size=20, color=(0, 0, 0, 1))
                            caption.refresh()
                            texture = caption.texture
                            texture_size = list(texture.size)
                            Rectangle(pos=(x,y), texture=texture, size=texture_size, group=group.name)
                    except Exception as ex:
                        # None may be returned if no regions in group
                        pass
                except AttributeError:
                    self.canvas.remove_group(group)

        self.app.removed_groups = []

    def draw_grid(self):
        self.resize_window()
        w,h = self.norm_image_size
        # normalized image floats in boxlayout so for a
        # nonsquare image there will be padding around
        # image, calculate amount and use as offset for
        # drawing grid
        self.offset_x = int((self.parent.size[0] - self.norm_image_size[0]) / 2)
        # print(self.parent.size[0], self.norm_image_size[1], self.size)
        self.offset_y = int((self.parent.size[0] - self.norm_image_size[1]) / 2)
        # [750.0, 516.0] [1000, 750] [750.0, 516.0] (688.0, 516.0)
        # print(self.parent.size, self.texture_size, self.size, self.norm_image_size)
        # print(self.offset_x, self.offset_y,)

        w = int(w)
        h = int(h)
        self.canvas.remove_group('grid')

        with self.canvas:
            Color(128, 128, 128, 0.5)

            if self.cols is not None:
                for col in range(0, w, self.col_spacing):
                    # for line 0 coordinate is bottom of screen?
                    # h (ie entire height) is top...
                    Line(points=[col + self.offset_x, 0 + self.offset_y, col + self.offset_x, h + self.offset_y], width=1, group='grid')
                    # debug from 0,0
                    # Line(points=[0, 0, col + self.offset_x, h + self.offset_y], width=1, group='grid')

            if self.rows is not None:
                for row in range(0, h, self.row_spacing):
                    #Line(points=[0 + self.offset_x, row, w + self.offset_x, row], width=1, group='grid')
                    # debug from 0,0
                    Line(points=[0 + self.offset_x, row + self.offset_y, w + self.offset_x, row + self.offset_y], width=1, group='grid')
                    # Line(points=[0, 0, w + self.offset_x, row], width=1, group='grid')

    def draw_geometry(self):
        self.clear_grid()

        with self.canvas:
            Color(128, 128, 128, 0.5)
            for rect in self.geometry:
                x,y,w,h = rect
                Rectangle(pos=(x,y), size=(w, h),group='selections')

    def draw_selection_click(self, x, y, color=None):
        # dot color not correct using color kwarg
        if color is None:
            color = (128, 128, 128, 0.5)
        dotsize = 20
        with self.canvas:
            Ellipse(pos=(x - (dotsize / 2), y - (dotsize / 2)), size=(dotsize, dotsize), group='clicks', color=color)
            caption = CoreLabel(text="{} {}".format(int(round(x)), int(round(y))), font_size=20, color=(0, 0, 0, 1))
            caption.refresh()
            texture = caption.texture
            texture_size = list(texture.size)
            Rectangle(pos=(x,y), texture=texture, size=texture_size, group="clicks")

    def draw_grid_click(self, x, y):
        # w, h = self.texture_size
        w,h = self.norm_image_size
        w = int(w)
        h = int(h)
        group = None
        # check in 'plus' pattern for adding
        # to existing group
        #       [X]
        #    [X][X][X]
        #       [X]
        for g in self.app.groups:
            if g.bounding_contains_point(x, y):
                group = g
            elif g.bounding_contains_point(x + self.col_spacing, y):
                group = g
            elif g.bounding_contains_point(x - self.col_spacing, y):
                group = g
            elif g.bounding_contains_point(x, y + self.row_spacing):
                group = g
            elif g.bounding_contains_point(x, y - self.row_spacing):
                group = g

        if group is None:
            group = Group()
            group.name = str(uuid.uuid4())
            group.color = colour.Color(pick_for=group)
            group.source_dimensions = [w, h]#[self.width, self.height]
            group.source = self.source_hash
            group.source_width = self.source_width
            group.source_height = self.source_height
            # since offset changes with image sizes,
            # store offset in group object so that outline
            # positions will be correctly drawn in ui
            group.display_offset_x = self.offset_x
            group.display_offset_y = self.offset_y
            self.group_container.add_group(group)

        Color(128, 128, 128, 0.5)
        dotsize = 10
        with self.canvas:
            Ellipse(pos=(x - (dotsize / 2), y - (dotsize / 2)), size=(dotsize, dotsize), group='clicks')
        # 0,0 is lower left corner
        for col in range(0 + self.offset_x, w + self.offset_x, self.col_spacing):
            for row in range(0 + self.offset_y, h + self.offset_y, self.row_spacing):
                if col < x and x < col + self.col_spacing:
                    if row < y and y < row + self.row_spacing:
                        rect = (col, row, self.col_spacing, self.row_spacing)
                        rect_points = (col, row, col + self.col_spacing, row + self.row_spacing)
                        if rect not in self.geometry:
                            with self.canvas:
                                Rectangle(pos=(col,row), size=(self.col_spacing, self.row_spacing), group="selections")
                            self.geometry.append(rect)
                            #x,y,w,h
                            if not rect_points in group.regions:
                                group.regions.append(rect_points)
                        else:
                            self.geometry.remove(rect)
                            try:
                                group.regions.remove(rect_points)
                            except ValueError as ex:
                                print(ex)
                                pass
                            self.draw_geometry()
        if group not in self.app.groups:
            self.app.groups.append(group)

        self.group_container.update_group(group.name)
        self.draw_groups()

    def draw_grid_click_segment(self, x, y, x2, y2, axis):
        w, h = self.texture_size
        # some squares are not being correctly clicked
        x = int(round(x))
        x2 = int(round(x2))
        y = int(round(y))
        y2 = int(round(y2))

        if axis == "x":
            if x > x2:
                start = x2
                end = x
            else:
                start = x
                end = x2
            for c in range(start, end, self.col_spacing):
                offset = 0
                self.draw_grid_click(c + offset, y)

        if axis == "y":
            if y > y2:
                start = y2
                end = y
            else:
                start = y
                end = y2
            for c in range(start, end, self.row_spacing):
                offset = 0
                self.draw_grid_click(x, c + offset)

    def draw_grid_click_line(self, x, y, axis, end_x=None, end_y=None):
        w, h = self.texture_size

        if axis == "x":
            for c in range(0, w, self.row_spacing):
                self.draw_grid_click(c + 2, y)

        if axis == "y":
            for c in range(0, h, self.col_spacing):
                self.draw_grid_click(x, c + 2)

    def handle_keybinds(self, keycode, modifiers):
        # this will cause problems typing
        # check that no focus on text input 
        # widgets
        #
        # something is not updating correctly
        # spacebar must be pressed twice on
        # start
        if keycode[1] == "spacebar":
            self.geometry = []
            self.clear_grid()
            self.draw_groups()
        elif keycode[1] == "down" and 'ctrl' in modifiers:
            self.row_spacing += 10
            self.col_spacing += 10
        elif keycode[1] == "up" and 'ctrl' in modifiers:
            self.row_spacing -= 10
            self.col_spacing -= 10
        # elif keycode[1] == "right":
        #     self.col_spacing -= 10
        # elif keycode[1] == "left":
        #     self.col_spacing += 10
        self.draw_grid()

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):

        if touch.grab_current is self:
            try:
                if touch.button == 'right':
                    # choose an selection / deselection axis
                    # by using the greater delta of x or y
                    if abs(touch.dsx) > abs(touch.dsy):
                        self.draw_grid_click_line(touch.x, touch.y, "x")
                    elif abs(touch.dsy) > abs(touch.dsx):
                        self.draw_grid_click_line(touch.x, touch.y, "y")
                elif touch.button == 'left':
                    if self.selection_mode is True:
                        self.selection_mode_selections.extend([int(round(touch.x)), int(round(touch.y))])
                        self.draw_selection_click(touch.x, touch.y, color=(self.selection_mode_group.group.color.rgb, 1))
                        if len(self.selection_mode_selections) >= 4:
                            # have enough points to draw rectangle
                            # set group region(s) and reset/leave selection_mode
                            self.selection_mode_group.group.regions = [self.selection_mode_selections[:4]]
                            self.selection_mode_group.update_group_display()
                            self.selection_mode = False
                            self.selection_mode_group = None
                            self.redraw()
                    else:
                        self.draw_grid_click(touch.x, touch.y)
                elif touch.button == 'middle':
                    if abs(touch.dsx) > abs(touch.dsy):
                        self.draw_grid_click_segment(touch.opos[0], touch.opos[1], touch.x, touch.y, "x")
                    elif abs(touch.dsy) > abs(touch.dsx):
                        self.draw_grid_click_segment(touch.opos[0], touch.opos[1], touch.x, touch.y, "y")
            except AttributeError as ex:
                # if exception:
                # 'ClickableImage' object has no attribute 'group_container'
                # clicked image is a thumbnail, update working image
                # with thumbnail's texture
                if touch.button == 'left':
                    self.app.change_working_image(self)
                elif touch.button == 'right':
                    # easiest multitouch right click involves
                    # right click on thumbnail, then slightly
                    # dragging the red dot with left button held
                    # down and releasing left button

                    # initial add of scatterlayout does not resize
                    # correcly, so only add scatter/image once a
                    # thumbnail has been selected
                    try:
                        if self.app.overlay_image not in self.app.overlay_container.children:
                            self.app.overlay_container.add_widget(self.app.overlay)
                    except:
                        #kivy.uix.widget.WidgetException
                        pass

                    self.app.overlay_image.texture = self.texture
                    self.app.overlay_image.size = self.texture_size
                    self.app.overlay_container.size = self.texture_size
                    print(self.app.overlay_container.size , self.app.overlay_image.size, self.app.overlay_image.norm_image_size)

                    self.app.overlay_image.draw_groups()
            touch.ungrab(self)
            return True
                    
        return super().on_touch_up(touch)

def bimg_resized(uuid, new_size, linking_uuid=None):
    contents = binary_r.get(uuid)
    f = io.BytesIO()
    f = io.BytesIO(contents)
    img = PImage.open(f)
    original_size = img.size
    img.thumbnail((new_size, new_size), PImage.ANTIALIAS)
    extension = img.format
    if linking_uuid:
        data_model_string = data_models.pretty_format(redis_conn.hgetall(linking_uuid), linking_uuid)
        # escape braces
        data_model_string = data_model_string.replace("{","{{")
        data_model_string = data_model_string.replace("}","}}")
        img = data_models.img_overlay(img, data_model_string, 50, 50, 12)
    file = io.BytesIO()
    img.save(file, extension)
    img.close()
    file.seek(0)

    filehash = hashlib.new('sha256')
    filehash.update(f.getvalue())

    return file, filehash, original_size

class TabItem(TabbedPanelItem):
    def __init__(self, root=None, **kwargs):
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_keyboard_down)
        self.root = root
        super(TabItem , self).__init__(**kwargs)

    def _keyboard_closed(self):
        # do not unbind the keyboard because
        # if keyboard is requested by textinput
        # widget, this keyboard used for app keybinds
        # will be unbound and not rebound after
        # defocusing textinput widget
        #
        # self._keyboard.unbind(on_key_down=self._on_keyboard_down)
        # self._keyboard = None
        pass

    def _on_keyboard_down(self, keyboard, keycode, text, modifiers):
        if keycode[1] == 'right' and 'shift' in modifiers:
            for i, c in enumerate(self.parent.children):
                if c == self.root.current_tab:
                    if i > 0:
                        self.root.switch_to(self.parent.children[i-1], do_scroll=True)
                        break
                    else:
                        self.root.switch_to(self.parent.children[len(self.parent.children)-1], do_scroll=True)
                        break
        elif keycode[1] == 'left' and 'shift' in modifiers:
            for i, c in enumerate(self.parent.children):
                if c == self.root.current_tab:
                    try:
                        self.root.switch_to(self.parent.children[i+1], do_scroll=True)
                        break
                    except IndexError as ex:
                        self.root.switch_to(self.parent.children[0], do_scroll=True)
                        break
        elif keycode[1] == 'c' and 'ctrl' in modifiers:
            # self.root.app.save_session()
            App.get_running_app().stop()
        else:
            for i, c in enumerate(self.parent.children):
                if c == self.root.current_tab:
                    try:
                        for widget in c.keybindings:
                            widget.handle_keybinds(keycode, modifiers)
                    except Exception as ex:
                        print(ex)

class TabbedPanelContainer(TabbedPanel):
    def __init__(self, **kwargs):
        super(TabbedPanelContainer, self).__init__()

class ColorPickerPopup(Popup):
    def __init__(self, **kwargs):
        self.title = "foo"
        self.content = ColorPicker()
        self.size_hint = (.5,.5)
        super(ColorPickerPopup, self).__init__()

class FileChooserPopup(Popup):
    def __init__(self, **kwargs):
        self.title = "choose file"
        self.content = FileChooserListView()
        self.size_hint = (.5,.5)
        super(FileChooserPopup, self).__init__()

class ChecklistApp(App):
    def __init__(self, *args,**kwargs):
        self.title="dss"
        self.resize_size = 1000
        self.thumbnail_height = 250
        self.thumbnail_width = 250
        self.working_image_height = 400
        self.working_image_width = 400
        self.pipe_env = {"key" : "binary_key", "key_prefix" : "binary:"}
        self.groups = []
        self.removed_groups = []
        self.project = {}
        self.project_widgets = {}
        self.objects_to_add = {}
        self.containers = {}
        self.session = {}
        self.session_save_path = "~/.config/dss/"
        self.session_save_filename = "session.xml"
        # if no previous session, load a few thumbs
        self.initial_random_thumbs = 2
        self.restore_session = True
        self.xml_files_to_load = []

        if 'xml_file' in kwargs:
            if kwargs['xml_file']:
                self.xml_files_to_load = kwargs['xml_file']
                self.restore_session = False

        if 'force_restore' in kwargs:
            if kwargs['force_restore'] is True:
                self.restore_session = True

        super(ChecklistApp, self).__init__()

    def dump_session(self):
        try:
            self.session['working_image'] = self.working_image.source_path
        except AttributeError as ex:
            pass

        try:
            for img in self.thumbnails.children:
                if not 'working_thumbs' in self.session:
                    self.session['working_thumbs'] = set()
                self.session['working_thumbs'].add(img.source_path)
        except AttributeError as ex:
            pass

    def grid_input(self, widget, slide_widget):
        try:
            value = int(widget.text)
            self.working_image.row_spacing = value
            self.working_image.col_spacing = value
            slide_widget.value = value
            self.grid_slide(slide_widget, widget)
        except ValueError as ex:
            pass

    def grid_slide(self, widget, input_widget):
        self.working_image.row_spacing = widget.value
        self.working_image.col_spacing = widget.value
        input_widget.text = str(widget.value)
        self.working_image.draw_grid()

    def file_binary(self, filename):
        data = io.BytesIO()
        with open(filename, "rb") as f:
            data = io.BytesIO(f.read())
        return self.bytes_binary(data.getvalue())

    def bytes_binary(self, data):
        # almost same code as bimg_resized
        new_size = self.resize_size
        f = io.BytesIO()
        f = io.BytesIO(data)
        img = PImage.open(f)
        original_size = img.size
        img.thumbnail((new_size, new_size), PImage.ANTIALIAS)
        extension = img.format
        file = io.BytesIO()
        img.save(file, extension)
        img.close()
        file.seek(0)

        filehash = hashlib.new('sha256')
        filehash.update(f.getvalue())

        img = ClickableImage(source_hash=filehash.hexdigest(),
                             allow_stretch=True,
                             keep_ratio=True)
        img.texture = CoreImage(file, ext="jpg", keep_data=True).texture
        img.source_width = original_size[0]
        img.source_height = original_size[1]
        img.app = self
        return img

    def glworb_binary(self, glworb=None):
        binary_keys = ["binary_key", "binary", "image_binary_key"]

        if glworb is None:
            try:
                glworb = random.choice(data_models.enumerate_data(pattern="glworb:*"))
            except IndexError:
                pass

        for bkey in binary_keys:
            data = redis_conn.hget(glworb, bkey)
            if data:
                print("{} has data".format(bkey))
                break

        filehash = None

        try:
            data, filehash, source_size = bimg_resized(data, self.resize_size, linking_uuid=glworb)
        except OSError as ex:
            print(ex)
            data = None

        if not data:
            placeholder = PImage.new('RGB', (self.resize_size, self.resize_size), (155, 155, 155, 1))
            source_size = (self.resize_size, self.resize_size)
            data_model_string = data_models.pretty_format(redis_conn.hgetall(glworb), glworb)
            if not data_model_string:
                data_model_string = glworb
            placeholder = data_models.img_overlay(placeholder, data_model_string, 50, 50, 12)
            file = io.BytesIO()
            placeholder.save(file, 'JPEG')
            placeholder.close()
            file.seek(0)
            data = file

            filehash = hashlib.new('sha256')
            filehash.update(file.getvalue())

        img = ClickableImage(source_hash=filehash.hexdigest(),
                             source_path = glworb,
                             allow_stretch=True,
                             keep_ratio=True)
        img.texture = CoreImage(data, ext="jpg", keep_data=True).texture
        img.source_width, img.source_height = source_size
        img.app = self
        return img

    def pick_file(self,*args):
        file_picker = FileChooserPopup()
        #file_picker.content.bind(color=self.on_color)
        file_picker.open()

    def add_glworb(self, glworb_id, display_widget=None):
        if display_widget is None:
            display_widget = self.thumbnails
        img = self.glworb_binary(glworb=glworb_id)
        self.thumbs_info.add_thumb(img)
        print(img)
        display_widget.add_widget(img)
        img.width = self.thumbnail_width
        img.height = self.thumbnail_height
        display_widget.width += img.width

    def change_from_thumb(self, thumb):
        self.change_working_image(thumb)
        self.glworb_info.update(thumb.source_path)
        self.thumbnails.parent.scroll_to(thumb)

    def remove_from_thumbs(self, thumb_hash):
        new_thumb_position = 0
        for i, thumb in enumerate(self.thumbnails.children):
            if thumb.source_hash == thumb_hash:
                self.thumbnails.remove_widget(thumb)
                new_thumb_position = i - 1
                break

        if self.working_image.source_hash == thumb_hash:
            try:
                self.change_working_image(self.thumbnails.children[new_thumb_position])
            except IndexError:
                self.working_image.hide()

        try:
            self.glworb_info.update(self.thumbnails.children[new_thumb_position].source_path)
        except IndexError:
            self.glworb_info.update(None)

    def add_binaries(self, add_method, output_label, display_widget, *args):
        tmp_output_filename = "/tmp/slurped_{}.jpg".format(str(uuid.uuid4()))
        process_feedback = ""

        def file_bytes(filename):
            contents = io.BytesIO()
            try:
                with open(filename, "rb") as f:
                    contents = io.BytesIO(f.read())
                return contents.getvalue()
            except FileNotFoundError:
                return b''

        if add_method == "slurp":
            try:
                output = subprocess.check_output(["ma-throw", "slurp"]).decode()
                process_feedback = output
            except subprocess.CalledProcessError as ex:
                process_feedback = str(ex)
                output = None

            if output:
                glworbs = [s for s in process_feedback.split("'") if "glworb:" in s]
                for g in glworbs:
                    img = self.glworb_binary(glworb=g)
                    display_widget.add_widget(img)
                    self.thumbs_info.add_thumb(img)
                    img.width = self.thumbnail_width
                    img.height = self.thumbnail_height
                    display_widget.width += img.width
                process_feedback = " ".join(glworbs)
        elif add_method == "webcam":
            addr = "/dev/video0"
            try:
                subprocess.call(["fswebcam",
                                 "--no-banner",
                                 "--save",
                                 tmp_output_filename,
                                 "-d",
                                 addr,
                                 "-r",
                                 "1280x960"])
                contents = file_bytes(tmp_output_filename)
            except subprocess.CalledProcessError as ex:
                process_feedback = str(ex)
                contents = None

            if contents:
                process_feedback = tmp_output_filename
                img = self.bytes_binary(contents)
                display_widget.add_widget(img)
                self.thumbs_info.add_thumb(img)
                img.width = self.thumbnail_width
                img.height = self.thumbnail_height
                display_widget.width += img.width
        elif add_method == "gphoto2":
            try:
                output = subprocess.check_output(["gphoto2",
                                         "--capture-image-and-download",
                                         "--filename={}".format(tmp_output_filename),
                                         "--force-overwrite"]).decode()
                contents = file_bytes(tmp_output_filename)
            except subprocess.CalledProcessError as ex:
                process_feedback = str(ex)
                contents = None

            if contents:
                process_feedback = tmp_output_filename
                img = self.bytes_binary(contents)
                display_widget.add_widget(img)
                self.thumbs_info.add_thumb(img)
                img.width = self.thumbnail_width
                img.height = self.thumbnail_height
                display_widget.width += img.width

        output_label.text = str(process_feedback)

    def update_project_image(self):
        overview = visualizations.project_overview(self.project, Window.width, 50, orientation='horizontal', color_key=True)[1]
        self.project_image.texture = CoreImage(overview, ext="jpg", keep_data=True).texture

        dimensions = visualizations.project_dimensions(self.project, 500, 150, scale=5)[1]
        self.project_dimensions_image.texture = CoreImage(dimensions, ext="jpg", keep_data=True).texture
        self.project_dimensions_image.size = self.project_dimensions_image.texture_size

    def update_project_thumbnail(self):
        overview_thumbnail = visualizations.project_overview(self.project, int(self.project_image_thumbnail.parent.width), 25, orientation='horizontal', color_key=True)[1]
        self.project_image_thumbnail.texture = CoreImage(overview_thumbnail, ext="jpg", keep_data=True).texture
        self.project_image_thumbnail.size = self.project_image_thumbnail.texture_size

    def update_project_info(self, attribute, value):
        self.project[attribute] = value
        if attribute == "name":
            self.project_name_header.text = value
        self.update_project_image()

    def add_project_info(self, attribute, parent):
        c = BoxLayout(orientation="horizontal", size_hint_y=None)
        c.add_widget(Label(text=attribute, halign="left", height=50, size_hint_y=None, size_hint_x=None, font_size=20))
        new_attribute = DropDownInput(height=44, size_hint_y=None)
        new_attribute.bind(on_text_validate=lambda widget: self.update_project_info(attribute, widget.text))
        c.add_widget(new_attribute)
        parent.add_widget(c)

    def recheck_fields(self, dt):
        self.glworb_info.update_current()

    def change_working_image(self, new):
        self.working_image.texture = new.texture
        self.working_image.source_hash = new.source_hash
        self.working_image.source_width = new.source_width
        self.working_image.source_height = new.source_height

        try:
            self.working_image.source_path = new.source_path
        except AttributeError:
            pass
        self.working_image.draw_grid()
        try:
            self.glworb_info.update(new.source_path)
        except AttributeError as ex:
            pass
        self.thumbs_info.center_on(new)

    def save_defaults(self, output_filename=None, output_path=None):

        if output_filename is None:
            output_filename = "defaults.xml"

        if output_path is None:
            output_path = os.path.expanduser(self.session_save_path)

        output_file = os.path.join(output_path, output_filename)
        defaults = etree.Element("defaults")
        saved_names = {}
        saved_names["group"] = []
        saved_names["category"] = []

        try:
            for group in self.groups:
                default = etree.Element("default", type="group", name=group.name, color=group.color.hex_l)
                defaults.append(default)
                saved_names["group"].append(group.name)
        except AttributeError as ex:
            pass

        try:
            for category in self.categories:
                default = etree.Element("default", type="category", name=category.category.name, color=category.category.color.hex_l)
                defaults.append(default)
                saved_names["category"].append(category.category.name)
        except AttributeError as ex:
            pass

        # defaults
        try:
            for group_name, group_color in self.defaults["group"].items():
                default = etree.Element("default", type="group", name=group_name, color=group_color)
                if group_name not in saved_names["group"]:
                    defaults.append(default)
        except KeyError:
            pass

        try:
            for category_name, category_color in self.defaults["category"].items():
                default = etree.Element("default", type="category", name=category_name, color=category_color)
                if category_name not in saved_names["category"]:
                    defaults.append(default)
        except KeyError:
            pass

        defaults_root = etree.ElementTree(defaults)
        xml_filename = output_filename

        if not os.path.isdir(output_path):
            os.mkdir(output_path)

        print("saving defaults {} to {}".format(output_filename, output_path))
        defaults_root.write(output_file, pretty_print=True)

    def load_defaults(self, filename=None, path=None):
        # names will be available in dropdowns
        # if name is entered with matching color
        # set color to default
        self.defaults = {}
        if filename is None:
            filename = "defaults.xml"

        if path is None:
            path = os.path.expanduser(self.session_save_path)

        defaults_file = os.path.join(path, filename)
        defaults = {}
        if os.path.isfile(defaults_file):
            xml = etree.parse(defaults_file)
            for default in xml.xpath('//default'):
                default_type = str(default.xpath("./@type")[0])
                default_name = str(default.xpath("./@name")[0])
                default_color = str(default.xpath("./@color")[0])

                if default_type not in defaults:
                    defaults[default_type] = {}
                defaults[default_type][default_name] = default_color
        # load category colors & names
        # load group colors & names
        # load dropdowns with names
        self.defaults.update(defaults)

    def save_session(self):
        self.dump_session()
        self.save_defaults()
        # add hook to run on exit()
        expanded_path = os.path.expanduser(self.session_save_path)
        if not os.path.isdir(expanded_path):
            print("creating: {}".format(expanded_path))
            os.mkdir(expanded_path)
        print("saving xml")
        self.xml_generator.generate_xml(write_output=True, output_filename=self.session_save_filename, output_path=expanded_path, generate_preview=False)

    def load_session(self):
        self.load_defaults()
        files_to_restore = []

        if self.restore_session is True:
            session_file = os.path.join(self.session_save_path, self.session_save_filename)
            session_file = os.path.expanduser(session_file)
            files_to_restore.append(session_file)

        for file in self.xml_files_to_load:
            files_to_restore.append(file)

        session_xml = {}
        project_xml = {}

        if not "working_thumbs" in session_xml:
            session_xml['working_thumbs'] = set()

        for file in files_to_restore:
            if os.path.isfile(file):
                try:
                    xml = etree.parse(file)
                    for session in xml.xpath('//session'):
                        try:
                            session_xml['working_image'] = str(session.xpath("./@working_image")[0])
                        except IndexError:
                            pass

                        for child in session.getchildren():
                            try:
                                session_xml['working_thumbs'].add(str(child.xpath("./@source_path")[0]))
                            except Exception as ex:
                                pass

                    for project in xml.xpath('//project'):
                        for attribute in project.attrib:
                            project_xml[attribute] = project.get(attribute)

                        for group in project.xpath('//group'):
                            g = Group()
                            ### placeholder values, need to properly
                            ### encode in xml
                            g.display_offset_x = 0
                            g.display_offset_y = 0
                            g.source_dimensions = [1, 1]
                            g.source_width = 1
                            g.source_height = 1
                            ###
                            for attribute in group.attrib:
                                try:
                                    if attribute == "color":
                                        setattr(g, attribute, colour.Color(group.get(attribute)))
                                    else:
                                        setattr(g, attribute, group.get(attribute))
                                except Exception as ex:
                                    print(ex)
                                    print(attribute, group.get(attribute))

                            # use .// to regions local to group
                            for region in group.xpath('.//region'):
                                x = int(region.xpath("./@x")[0])
                                y= int(region.xpath("./@y")[0])
                                w = int(region.xpath("./@width")[0])
                                h = int(region.xpath("./@height")[0])
                                g.regions.append([x, y, x + w, y + h])
                                # store dimensions in thumb and lookup via group source?
                                #g.source_dimensions = (int(region.xpath("./@width"), int(region.xpath("./@width")))
                            if "group" not in self.objects_to_add:
                                self.objects_to_add['group'] = []
                            self.objects_to_add['group'].append(g)

                        for rule in project.xpath('//rule'):
                            r = Rule()
                            r.comparator_params = []
                            r.source_field = str(rule.xpath("./@source")[0])
                            r.dest_field = str(rule.xpath("./@destination")[0])
                            r.rule_result = str(rule.xpath("./@result")[0])
                            # handles multiple paramters but only a single symbol
                            for parameter in rule.xpath('.//parameter'):
                                r.comparator_symbol = str(parameter.xpath("./@symbol")[0])
                                r.comparator_params.append(parameter.xpath("./@values")[0])

                            if "rule" not in self.objects_to_add:
                                self.objects_to_add['rule'] = []
                            self.objects_to_add['rule'].append(r)

                        for category in project.xpath('//category'):
                            try:
                                rough_order = float(category.xpath("./@rough_order")[0])
                            except:
                                rough_order = 0
                            c = Category(name = str(category.xpath("./@name")[0]),
                                         color = colour.Color(str(category.xpath("./@color")[0])),
                                         rough_amount = int(category.xpath("./@rough_amount")[0]),
                                         rough_order = rough_order)
                            try:
                                c.rough_amount_start = category.xpath("./@rough_amount_start")[0]
                                c.rough_amount_end = category.xpath("./@rough_amount_end")[0]
                            except Exception as ex:
                                pass

                            if "category" not in self.objects_to_add:
                                self.objects_to_add['category'] = []
                            self.objects_to_add['category'].append(c)
                except etree.XMLSyntaxError as ex:
                    print("cannot parse xml from file: {}, ignoring".format(file))

        print(session_xml)
        print(project_xml)

        # update the session dictionary
        self.session.update(session_xml)

        # update the project dictionary
        self.project.update(project_xml)

        # separate config, but also to be loaded:
        # colors -> groups
        # colors -> categories

    def create_project_widgets(self, name, parent, reference_dict):
        # create input widgets for project attributes
        try:
            input_fill_text = self.project[name]
        except KeyError:
            input_fill_text = ""

        widgets = BoxLayout(orientation="horizontal", size_hint_y=None)
        label_widget = Label(text="{}:".format(name), halign="left", height=50, size_hint_y=None, size_hint_x=None, font_size=20)
        input_widget = TextInput(text=input_fill_text, multiline=False, height=50, size_hint_y=None, font_size=20)
        input_widget.bind(on_text_validate=lambda widget: self.update_project_info(name, widget.text))
        widgets.add_widget(label_widget)
        widgets.add_widget(input_widget)
        parent.add_widget(widgets)
        # set to input widget since that will have
        # text updated on load...
        reference_dict[name] = input_widget

    def build(self):

        groups_layout = GroupContainer(orientation='vertical', size_hint_y=None, height=self.working_image_height, minimum_height=self.working_image_height)
        groups_layout.app = self
        self.containers['group']= groups_layout

        categories_layout = CategoryContainer(orientation='vertical', size_hint_y=None, height=self.working_image_height, minimum_height=self.working_image_height)
        categories_layout.app = self
        self.containers['category']= categories_layout

        rules_layout = RuleContainer(orientation='vertical', size_hint_y=None, height=self.working_image_height, minimum_height=self.working_image_height)
        rules_layout.app = self
        self.containers['rule']= rules_layout

        self.load_session()
        root = TabbedPanel(do_default_tab=False)
        root.tab_width = 200
        root.app = self

        thumbnail_container = ScatterTextWidget()
        # use for recycleview item actions when calling
        # add_glworb
        self.thumbnails = thumbnail_container.image_grid
        self.working_image = None

        thumbs_layout = ThumbContainer(self, orientation='vertical', size_hint_y=None, height=800, minimum_height=50)
        self.thumbs_info = thumbs_layout

        # horizontal boxlayout, label and input is repetitive
        # move to function that accepts label text, bind call, ...
        project_container = BoxLayout(orientation='vertical', size_hint_y=None, height=1200, minimum_height=200)
        name_container = BoxLayout(orientation="horizontal", size_hint_y=None)

        project_image = Image(size_hint_y=None)
        project_dimensions_image = Image(size_hint_y=None)
        self.project_image = project_image
        self.project_dimensions_image = project_dimensions_image
        self.update_project_image()
        self.project_thumbnail_height = 25
        self.project_image_thumbnail = Image(height=self.project_thumbnail_height, size_hint_y=None)

        project_scroll = ScrollView(bar_width=20)
        project_scroll.add_widget(project_container)

        self.project_name_header = Label(text="")
        project_container.add_widget(self.project_name_header)
        project_container.add_widget(project_dimensions_image)
        project_container.add_widget(project_image)

        self.create_project_widgets("name", project_container, self.project_widgets)
        self.create_project_widgets("width", project_container, self.project_widgets)
        self.create_project_widgets("height", project_container, self.project_widgets)
        self.create_project_widgets("depth", project_container, self.project_widgets)
        self.create_project_widgets("units", project_container, self.project_widgets)
        self.create_project_widgets("standard", project_container, self.project_widgets)

        custom_container = BoxLayout(orientation="horizontal", size_hint_y=None)
        custom_container.add_widget(Label(text="custom:", halign="left", height=50, size_hint_y=None, size_hint_x=None, font_size=20))
        project_depth = DropDownInput(height=44, size_hint_y=None)
        project_depth.bind(on_text_validate=lambda widget: self.add_project_info(widget.text, project_container))
        custom_container.add_widget(project_depth)
        project_container.add_widget(custom_container)

        tab = TabItem(text="overview",root=root)
        tab.add_widget(project_scroll)
        root.add_widget(tab)

        tab = TabItem(text="image",root=root)
        tab_container = BoxLayout(orientation='horizontal')
        left_container = BoxLayout(orientation='vertical')
        right_container = BoxLayout(orientation='vertical')

        upper_container = BoxLayout(orientation='horizontal')
        lower_container = BoxLayout(orientation='horizontal', height=self.thumbnail_height, size_hint=(1,None))

        img_container = FloatLayout()
        tools_container = BoxLayout(orientation='vertical')

        groups_container = BoxLayout(orientation='horizontal')
        files_container = BoxLayout(orientation='horizontal')
        glworbs_container = BoxLayout(orientation='vertical')
        groups_scroll = ScrollView(bar_width=20)
        groups_scroll.add_widget(groups_layout)

        try:
            # try to load from session first
            # glworb only, need to check for filesystem too
            img = self.glworb_binary(glworb=self.session['working_image'])
        except Exception as ex:
            img = self.glworb_binary()
            self.session['working_image'] = img.source_path
            self.session['working_thumbs'].add(img.source_path)

        self.working_image = img
        img.group_container = groups_layout

        add_binary_output = Label(text="",font_size=12)
        slurp_button = Button(text="slurp (ma)", font_size=20)
        webcam_button = Button(text="webcam (shell)", font_size=20)
        gphoto2_button = Button(text="gphoto2 (shell)", font_size=20)

        slurp_button.bind(on_press=lambda x: self.add_binaries("slurp",
                                                               add_binary_output,
                                                               thumbnail_container.image_grid))
        webcam_button.bind(on_press=lambda x: self.add_binaries("webcam",
                                                               add_binary_output,
                                                               thumbnail_container.image_grid))
        gphoto2_button.bind(on_press=lambda x: self.add_binaries("gphoto2",
                                                               add_binary_output,
                                                               thumbnail_container.image_grid))
        button_container = BoxLayout(orientation='vertical')

        #actions_container.add_widget(slurp_button)
        files_container.add_widget(ClickableFileChooserListView(self))
        groups_container.add_widget(groups_scroll)

        tools_container.add_widget(self.project_image_thumbnail)
        self.update_project_thumbnail()
        sub_panel = TabbedPanel(do_default_tab=False)
        tools_container.add_widget(sub_panel)

        sub_tab = TabbedPanelItem(text="groups")
        b = BoxLayout(orientation='horizontal')
        slider_container = BoxLayout(orientation='vertical', size_hint_x=None)
        s = Slider(min=1, max=500, step=5, value=100, size_hint_x=None, orientation="vertical")
        slider_input = TextInput(size_hint_x=None, size_hint_y=None, multiline=False, height=30)
        slider_input.text = str(s.value)
        slider_container.add_widget(Label(text="grid size", size_hint_x=None, size_hint_y=None, height=30))
        slider_container.add_widget(slider_input)
        slider_container.add_widget(s)
        hide_working_img = Button(text="hide img", size_hint_x=None, size_hint_y=None, height=30)
        slider_container.add_widget(hide_working_img)
        b.add_widget(slider_container)
        s.bind(on_touch_move=lambda widget, touch:self.grid_slide(widget, slider_input))
        slider_input.bind(on_text_validate=lambda widget:self.grid_input(widget, s))
        hide_working_img.bind(on_press=lambda x: self.working_image.hide())
        b.add_widget(groups_container)
        sub_tab.add_widget(b)
        sub_panel.add_widget(sub_tab)

        sub_tab = TabbedPanelItem(text="categories")
        categories_scroll = ScrollView(bar_width=20)
        categories_scroll.add_widget(categories_layout)

        categories_container = BoxLayout(orientation='vertical')
        category_gen = CategoryGenerator(size_hint_y=None)
        category_gen.category_container = categories_layout
        categories_container.add_widget(categories_scroll)
        categories_container.add_widget(category_gen)
        category_gen.app = self
        self.category_gen = category_gen
        self.categories = categories_layout.categories
        sub_tab.add_widget(categories_container)
        sub_panel.add_widget(sub_tab)

        sub_tab = TabbedPanelItem(text="rules")
        rules_scroll = ScrollView(bar_width=20)
        rules_scroll.add_widget(rules_layout)

        rules_container = BoxLayout(orientation='vertical')
        rule_gen = RuleGenerator(self)
        rule_gen.rule_container = rules_layout
        rules_container.add_widget(rules_scroll)
        rules_container.add_widget(rule_gen)
        #rule_gen.app = self
        self.rule_gen = rule_gen
        self.rule_container = rules_layout
        sub_tab.add_widget(rules_container)
        sub_panel.add_widget(sub_tab)

        sub_tab = TabbedPanelItem(text="info")
        info_container = BoxLayout(orientation="vertical")
        self.glworb_info = GlworbInfo(self, size_hint_y=0.5)
        info_container.add_widget(self.glworb_info)
        thumbs_scroll = ScrollView(bar_width=20, size_hint_y=0.5)
        thumbs_scroll.add_widget(thumbs_layout)
        info_container.add_widget(thumbs_scroll)
        sub_tab.add_widget(info_container)
        sub_panel.add_widget(sub_tab)

        self.glworb_info.update(self.working_image.source_path)

        sub_tab = TabbedPanelItem(text="glworbs")
        glworb_filter = TextInput(multiline=False, size_hint_y=None, height=44)
        glworb_view = GlworbRecycleView()
        glworb_view.app = self
        # scrollbar width
        glworb_view.bar_width = 20
        glworb_view.app = self
        glworb_filter.bind(on_text_validate=lambda instance: [glworb_view.filter_view(instance.text), setattr(instance, 'background_color', (0, 1, 0, 1)) if instance.text else setattr(instance, 'background_color', (1, 1, 1, 1))])
        glworbs_container.add_widget(glworb_filter)
        add_filtered = BoxLayout(size_hint_y=None, height=44)
        add_filtered.add_widget(Label(text="Load all filtered, sorted by:", size_hint_y=None, height=44))
        add_sort_by = TextInput(multiline=False, size_hint_y=None, height=44)
        add_filtered.add_widget(add_sort_by)
        add_sort_by.bind(on_text_validate=lambda instance: glworb_view.mass_add(sort_by=instance.text))
        glworbs_container.add_widget(add_filtered)
        glworbs_container.add_widget(glworb_view)
        sub_tab.add_widget(glworbs_container)
        sub_panel.add_widget(sub_tab)

        sub_tab = TabbedPanelItem(text="files")
        sub_tab.add_widget(files_container)
        sub_panel.add_widget(sub_tab)

        sub_tab = TabbedPanelItem(text="slurp")
        button_container.add_widget(add_binary_output)
        button_container.add_widget(slurp_button)
        button_container.add_widget(webcam_button)
        button_container.add_widget(gphoto2_button)
        sub_tab.add_widget(button_container)
        sub_panel.add_widget(sub_tab)

        img_container.add_widget(img)

        image = OverlayImage(self)
        scatter = ScatterLayout()
        image.opacity = 0.5
        scatter.add_widget(image)
        #img_container.add_widget(scatter)
        scatter.size = image.size
        self.overlay_container = img_container
        self.overlay = scatter
        self.overlay_image = image
        # upper_container.add_widget(img_container)
        upper_container.add_widget(tools_container)


        left_container.add_widget(img_container)
        right_container.add_widget(upper_container)
        right_container.add_widget(lower_container)

        tab_container.add_widget(left_container)
        tab_container.add_widget(right_container)

        tab.add_widget(tab_container)
        tab.keybindings = []
        tab.keybindings.append(img)
        root.add_widget(tab)

        widgets_to_add = []
        # add working image to thumbnails
        # initial_working_image = self.glworb_binary(glworb=self.working_image.source_path)
        # self.thumbs_info.add_thumb(initial_working_image)
        # widgets_to_add.append(functools.partial(
        #                 thumbnail_container.image_grid.add_widget,
        #                 initial_working_image,
        #                 index=len(thumbnail_container.image_grid.children))
        #               )

        try:
            for thumb in self.session['working_thumbs']:
                print("loading thumb: {}".format(thumb))
                img = self.glworb_binary(glworb=thumb)
                self.thumbs_info.add_thumb(img)
                widgets_to_add.append(functools.partial(
                                        thumbnail_container.image_grid.add_widget,
                                        img,
                                        index=len(thumbnail_container.image_grid.children))
                                      )
        except Exception as ex:
            # add a few random thumbnails
            for _ in range(self.initial_random_thumbs):
                img = self.glworb_binary()
                self.thumbs_info.add_thumb(img)
                widgets_to_add.append(functools.partial(
                                        thumbnail_container.image_grid.add_widget,
                                        img,
                                        index=len(thumbnail_container.image_grid.children))
                                      )

        for widget in widgets_to_add:
            widget()

        lower_container.add_widget(thumbnail_container)
        tab.keybindings.append(thumbnail_container.scroller)

        for c in thumbnail_container.image_grid.children:
            print(c.size, c.width, c.height)
            c.width = self.thumbnail_width
            c.height = self.thumbnail_height
            thumbnail_container.image_grid.width += c.width
            if c.height > thumbnail_container.height:
                thumbnail_container.image_grid.height = c.height
                lower_container.height = c.height

        tab = TabItem(text="output",root=root)
        generated_xml = OutputPreview(self, size_hint=(1,1))
        self.xml_generator = generated_xml
        tab.add_widget(generated_xml)
        root.add_widget(tab)

        for k, v in self.objects_to_add.items():
            if k == 'group':
                for g in v:
                    self.containers['group'].add_group(g)
                    if g not in self.groups:
                        self.groups.append(g)
            elif k == 'rule':
                for r in v:
                    # inconsistent with add_group which handles Item
                    self.containers['rule'].add_rule(RuleItem(r))
            elif k == 'category':
                for c in v:
                    self.containers['category'].add_category(c)

        # call to update thumbnails and project image using
        # loaded categories if any
        self.containers['category'].update()

        Clock.schedule_interval(self.recheck_fields, 30)
        # draw initial grid on working image
        # using a clock since immediately
        # drawing results in wrong dimensions
        Clock.schedule_once(lambda x: self.working_image.draw_grid(), 10)
        Clock.schedule_once(lambda x: self.update_project_thumbnail(), 10)

        return root

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml-file", nargs='+', default=[], help="xml file(s) to load on startup (session will not be restored)")
    parser.add_argument("--force-restore", action='store_true', help="restore session even if loading xml")
    args = parser.parse_args()
    app = ChecklistApp(**vars(args))
    atexit.register(app.save_session)
    app.run()
