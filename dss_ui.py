# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2018, Galen Curwen-McAdams

import random
import io
import functools
import subprocess
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.config import Config
from kivy.graphics.vertex_instructions import Rectangle
from kivy.graphics import Color, Line, Ellipse, InstructionGroup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.colorpicker import ColorPicker
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.uix.textinput import TextInput
from kivy.uix.accordion import Accordion, AccordionItem
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from PIL import Image as PImage
import redis
import attr
import uuid
import colour
from ma_cli import data_models

r_ip, r_port = data_models.service_connection()
binary_r = redis.StrictRedis(host=r_ip, port=r_port)
r = redis.StrictRedis(host=r_ip, port=r_port, decode_responses=True)

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
"""

Builder.load_string(kv)

@attr.s
class Group(object):
    regions = attr.ib(default=attr.Factory(list))
    color = attr.ib(default=None)
    name = attr.ib(default="")

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
        print(touch.button)
        if touch.button == 'left':
            return super().on_touch_down(touch)
        elif touch.button == 'scrollup':
            self.enlarge()
        elif touch.button == 'scrolldown':
            self.shrink()
    pass

class GroupItem(BoxLayout):
    def __init__(self,**kwargs):
        self.group = None
        self.initial_update = False
        super(GroupItem, self).__init__(**kwargs)

    def update_group_display(self):
        if self.initial_update:
            self.group_region.text = str(self.group.bounding_rectangle)
            self.group_color.color = self.group.color.rgb
        else:
            group_color = Button(text= "@@@", font_size=20, color=self.group.color.rgb)
            group_color.bind(on_press=self.pick_color)
            group_name = TextInput(text=self.group.name, multiline=False, font_size=20, background_color=(.6, .6, .6, 1))
            group_region = Label(text=str(self.group.bounding_rectangle))
            group_name.bind(on_text_validate=functools.partial(self.on_text_enter))
            self.add_widget(group_color)
            self.add_widget(group_name)
            self.add_widget(group_region)
            self.group_region = group_region
            self.group_color = group_color
            self.initial_update = True

    def pick_color(self,*args):
        color_picker = ColorPickerPopup()
        color_picker.content.bind(color=self.on_color)
        color_picker.open()

    def on_color(self, instance, *args):
        self.group.color.rgb = instance.color[:3]
        self.update_group_display()

    def on_text_enter(self, instance, *args):
        print(instance.text, args)
        self.group.name = instance.text

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
        g = GroupItem()
        g.group = group
        g.update_group_display()
        self.add_widget(g)

    def remove_group(self, name):
        for group in self.children:
            try:
                if group.group.name == name:
                    self.remove_widge(group)
            except AttributeError:
                pass

class ClickableImage(Image):
    def __init__(self, **kwargs):
        self.rows = 0
        self.cols = 0
        self.row_spacing = 100
        self.col_spacing = 100
        self.offset_x = 0
        self.offset_y = 0
        self.offset_top = 0
        self.geometry = []
        self.app = None
        self.resized = False
        super(ClickableImage, self).__init__(**kwargs)

    def resize_window(self, *args):
        # only resize once...
        if self.resized is False:
            # w, h = self.norm_image_size
            # w = int(w)
            # h = int(h)
            # Window.size = w * 2, h
            self.resized = True

    def clear_grid(self):
        self.canvas.remove_group('selections')
        self.canvas.remove_group('clicks')

    def draw_groups(self):
        with self.canvas:
            for group in self.app.groups:
                self.canvas.remove_group(group.name)
                # Color(128, 128, 128, 0.5)
                Color(*group.color.rgb, 0.5)
                try:
                    for x, y, w, h in [group.bounding_rectangle]:
                        Rectangle(pos=(x,y), size=(w, h), group=group.name)
                except Exception as ex:
                    # None may be returned if no regions in group
                    pass

    def draw_grid(self):
        self.resize_window()

        w,h = self.norm_image_size
        # normalized image floats in boxlayout so for a
        # nonsquare image there will be padding around
        # image, calculate amount and use as offset for
        # drawing grid

        self.offset_x = int((self.parent.size[0] - self.norm_image_size[0]) / 2)
        self.offset_y = int((self.parent.size[0] - self.norm_image_size[1]) / 2)
        # [750.0, 516.0] [1000, 750] [750.0, 516.0] (688.0, 516.0)
        # print(self.parent.size, self.texture_size, self.size, self.norm_image_size)
        # print(self.offset_x, self.offset_y,)
        self.offset_top = int(abs(self.parent.top - Window.size[1]))
        w = int(w)
        h = int(h)
        self.canvas.remove_group('grid')

        with self.canvas:
            Color(128, 128, 128, 0.5)

            if self.cols is not None:
                for col in range(0, w, self.col_spacing):
                    # for line 0 coordinate is bottom of screen?
                    # h (ie entire height) is top...
                    Line(points=[col + self.offset_x, 0, col + self.offset_x, h], width=1, group='grid')
                    # debug from 0,0
                    #Line(points=[0, 0, col + self.offset_x, h + self.offset_y + self.offset_top], width=1, group='grid')

            if self.rows is not None:
                for row in range(0, h, self.row_spacing):
                    Line(points=[0 + self.offset_x, row, w + self.offset_x, row], width=1, group='grid')
                    # debug from 0,0
                    #Line(points=[0, 0, w + self.offset_x, row], width=1, group='grid')

    def draw_geometry(self):
        self.clear_grid()

        with self.canvas:
            Color(128, 128, 128, 0.5)
            for rect in self.geometry:
                x,y,w,h = rect
                Rectangle(pos=(x,y), size=(w, h),group='selections')

    def draw_grid_click(self, x, y):
        w, h = self.texture_size
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
            self.group_container.add_group(group)

        Color(128, 128, 128, 0.5)
        dotsize = 10
        with self.canvas:
            Ellipse(pos=(x - (dotsize / 2), y - (dotsize / 2)), size=(dotsize, dotsize), group='clicks')
        # 0,0 is lower left corner
        for col in range(0 + self.offset_x, w + self.offset_x, self.col_spacing):
            for row in range(0, h + self.offset_y + self.offset_top, self.row_spacing):
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
                    self.draw_grid_click(touch.x, touch.y)
                elif touch.button == 'middle':
                    if abs(touch.dsx) > abs(touch.dsy):
                        self.draw_grid_click_segment(touch.opos[0], touch.opos[1], touch.x, touch.y, "x")
                    elif abs(touch.dsy) > abs(touch.dsx):
                        self.draw_grid_click_segment(touch.opos[0], touch.opos[1], touch.x, touch.y, "y")
            except AttributeError as ex:
                print(ex)

            touch.ungrab(self)
            return True

            # p = touch.pos 
            # o = touch.opos 
            # s = min(p[0],o[0]), min(p[1],o[1]), abs(p[0]-o[0]), abs(p[1]-o[1])
            # s = min(p[0],o[0]), min(p[1],o[1]), abs(p[0]-o[0]), abs(p[1]-o[1])
            # w  = s[2]
            # h  = s[3]
            # sx = s[0]
            # sy = s[1]
            # if abs(w) > 5 and abs(h) >5:
            #     if self.collide_point(touch.pos[0],touch.pos[1]):
            #         #self.add_widget(Selection(pos=(sx,sy),size=(w, h)))
            #         #self.canvas.add(Rectangle(pos=(sx,sy),size=(w, h),color=(155,155,155,0.5)))

            #         #because getting resized image no knowldge of original geometry
            #         #for scaling...

            #         print("added widget for ",self)
            #         print(self.texture_size,self.norm_image_size,self.size)
            #         # width_scale  = self.texture_size[0] / self.norm_image_size[0]
            #         # height_scale = self.texture_size[1] / self.norm_image_size[1]
            #         x = touch.opos[0]
            #         y = abs(touch.opos[1]-self.norm_image_size[1])
            #         w = touch.pos[0]-touch.opos[0]
            #         h =abs(touch.pos[1]-self.norm_image_size[1])-abs(touch.opos[1]-self.norm_image_size[1])

            #         print(x,y,w,h)
            #         px = x / self.norm_image_size[0]
            #         py = y / self.norm_image_size[1]
            #         pw = w / self.norm_image_size[0]
            #         ph = h / self.norm_image_size[1]

            #         # print(Window.size)
            #         print(px,py,pw,ph)
            #         print(px*self.norm_image_size[0],py*self.norm_image_size[1],pw*self.norm_image_size[0],ph*self.norm_image_size[1])
            #         percents= "{} {} {} {}".format(px,py,pw,ph)
                    
        return super().on_touch_up(touch)

def bimg_resized(uuid, new_size, linking_uuid=None):
    contents = binary_r.get(uuid)
    f = io.BytesIO()
    f = io.BytesIO(contents)
    img = PImage.open(f)
    img.thumbnail((new_size, new_size), PImage.ANTIALIAS)
    extension = img.format
    if linking_uuid:
        data_model_string = data_models.pretty_format(r.hgetall(linking_uuid), linking_uuid)
        # escape braces
        data_model_string = data_model_string.replace("{","{{")
        data_model_string = data_model_string.replace("}","}}")
        img = data_models.img_overlay(img, data_model_string, 50, 50, 12)
    file = io.BytesIO()
    img.save(file, extension)
    img.close()
    file.seek(0)
    #return file.getvalue()
    return file

class TabItem(TabbedPanelItem):
    def __init__(self, root=None, **kwargs):
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self)
        self._keyboard.bind(on_key_down=self._on_keyboard_down)
        self.root = root
        super(TabItem , self).__init__(**kwargs)

    def _keyboard_closed(self):
        self._keyboard.unbind(on_key_down=self._on_keyboard_down)
        self._keyboard = None

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
        self.resize_size = 1000
        self.thumbnail_height = 400
        self.thumbnail_width = 400
        self.groups = []
        super(ChecklistApp, self).__init__()

    def bytes_binary(self, data):
        # almost same code as bimg_resized
        new_size = self.resize_size
        f = io.BytesIO()
        f = io.BytesIO(data)
        img = PImage.open(f)
        img.thumbnail((new_size, new_size), PImage.ANTIALIAS)
        extension = img.format
        file = io.BytesIO()
        img.save(file, extension)
        img.close()
        file.seek(0)

        img = ClickableImage(
                             allow_stretch=True,
                             keep_ratio=True)
        img.texture = CoreImage(file, ext="jpg", keep_data=True).texture
        img.app = self
        return img

    def glworb_binary(self, glworb=None):
        binary_keys = ["binary_key", "binary", "image_binary_key"]

        if glworb is None:
            glworb = random.choice(data_models.enumerate_data(pattern="glworb:*"))

        for bkey in binary_keys:
            data = r.hget(glworb, bkey)
            if data:
                print("{} has data".format(bkey))
                break
        try:
            data = bimg_resized(data, self.resize_size, linking_uuid=glworb)
        except OSError as ex:
            print(ex)
            data = None

        if not data:
            placeholder = PImage.new('RGB', (self.resize_size, self.resize_size), (155, 155, 155, 1))
            data_model_string = data_models.pretty_format(r.hgetall(glworb), glworb)
            if not data_model_string:
                data_model_string = glworb
            placeholder = data_models.img_overlay(placeholder, data_model_string, 50, 50, 12)
            file = io.BytesIO()
            placeholder.save(file, 'JPEG')
            placeholder.close()
            file.seek(0)
            data = file

        img = ClickableImage(
                             allow_stretch=True,
                             keep_ratio=True)
        img.texture = CoreImage(data, ext="jpg", keep_data=True).texture
        img.app = self
        return img

    def pick_file(self,*args):
        file_picker = FileChooserPopup()
        #file_picker.content.bind(color=self.on_color)
        file_picker.open()

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
                img.width = self.thumbnail_width
                img.height = self.thumbnail_height
                display_widget.width += img.width

        output_label.text = str(process_feedback)

    def build(self):

        root = TabbedPanel(do_default_tab=False)
        root.tab_width = 200

        thumbnail_container = ScatterTextWidget()

        tab = TabItem(text="overview",root=root)
        root.add_widget(tab)

        tab = TabItem(text="image",root=root)
        tab_container = BoxLayout(orientation='vertical')
        upper_container = BoxLayout(orientation='horizontal')
        lower_container = BoxLayout(orientation='horizontal', height=800, size_hint=(1,1))

        img_container = BoxLayout(orientation='horizontal')
        categories_container = BoxLayout(orientation='vertical')

        groups_container = BoxLayout(orientation='horizontal')
        files_container = BoxLayout(orientation='horizontal')
        gc = GroupContainer(orientation='vertical')
        img = self.glworb_binary()
        img.group_container = gc
        add_binary_output = Label(text="",font_size=20)
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
        files_container.add_widget(FileChooserListView())
        groups_container.add_widget(gc)

        sub_panel = TabbedPanel(do_default_tab=False)
        categories_container.add_widget(sub_panel)
        sub_tab = TabbedPanelItem(text="groups")
        sub_tab.add_widget(groups_container)
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

        upper_container.add_widget(img_container)
        upper_container.add_widget(categories_container)

        tab_container.add_widget(upper_container)
        tab_container.add_widget(lower_container)

        tab.add_widget(tab_container)
        tab.keybindings = []
        tab.keybindings.append(img)
        root.add_widget(tab)

        widgets_to_add = []
        for _ in range(2):
            img = self.glworb_binary()
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
        # tab = TabItem(text="categories",root=root)
        # tab.add_widget(group_container)
        # root.add_widget(tab)
        return root

if __name__ == "__main__":
    ChecklistApp().run()    


