# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2018, Galen Curwen-McAdams

import random
import io
from kivy.app import App
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.config import Config
from kivy.graphics.vertex_instructions import Rectangle
from kivy.graphics import Color, Line, Ellipse, InstructionGroup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.uix.textinput import TextInput
from kivy.uix.accordion import Accordion, AccordionItem
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from PIL import Image as PImage
import redis
from ma_cli import data_models

r_ip, r_port = data_models.service_connection()
binary_r = redis.StrictRedis(host=r_ip, port=r_port)
r = redis.StrictRedis(host=r_ip, port=r_port, decode_responses=True)

Config.read('config.ini')

class ClickableImage(Image):
    def __init__(self, **kwargs):
        self.rows = 0
        self.cols = 0
        self.row_spacing = 100
        self.col_spacing = 100
        self.geometry = []
        self.selected = InstructionGroup()
        super(ClickableImage, self).__init__(**kwargs)

    def draw_rows(self):
        pass

    def draw_cols(self):
        pass

    def clear_grid(self):
        self.canvas.remove_group('selections')
        self.canvas.remove_group('clicks')

    def draw_grid(self):
        w, h = self.texture_size
        if self.cols is None:
            self.col_spacing = w

        if self.rows is None:
            self.row_spacing = w
        # this will clear image too
        # self.canvas.clear()
        with self.canvas:
            Color(128, 128, 128, 0.5)

            if self.cols is not None:
                for col in range(0, h, self.col_spacing):
                    Line(points=[col, 0, col, h], width=2)

            if self.rows is not None:
                for row in range(0, w, self.row_spacing):
                    Line(points=[0, row, w, row], width=2)

    def draw_geometry(self):
        self.clear_grid()

        with self.canvas:
            Color(128, 128, 128, 0.5)
            for rect in self.geometry:
                x,y,w,h = rect
                Rectangle(pos=(x,y), size=(w, h),group='selections')

    def draw_grid_click(self, x, y):
        w, h = self.texture_size
        #with self.canvas:
        Color(128, 128, 128, 0.5)
        dotsize = 10
        with self.canvas:
            Ellipse(pos=(x - (dotsize / 2), y - (dotsize / 2)), size=(dotsize, dotsize), group='clicks')
        for col in range(0, w, self.col_spacing):
            for row in range(0, h, self.row_spacing):
                if col < x and x < col + self.col_spacing:
                    if row < y and y < row + self.row_spacing:
                        rect = (col, row, self.col_spacing, self.row_spacing)
                        if rect not in self.geometry:
                            with self.canvas:
                                Rectangle(pos=(col,row), size=(self.col_spacing, self.row_spacing), group="selections")
                            self.geometry.append(rect)
                        else:
                            self.geometry.remove(rect)
                            self.draw_geometry()

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

    def handle_keybinds(self, key):
        # this will cause problems typing
        # check that no focus on text input 
        # widgets
        if key == "spacebar":
            self.geometry = []
            self.clear_grid()

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.grab(self)
            return True

    def on_touch_up(self, touch):

        if touch.grab_current is self:
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
        elif keycode[1] == 'spacebar':
            for i, c in enumerate(self.parent.children):
                if c == self.root.current_tab:
                    try:
                        c.keybindings.handle_keybinds("spacebar")
                    except Exception as ex:
                        print(ex)
        elif keycode[1] == 'c' and 'ctrl' in modifiers:
            App.get_running_app().stop()

class TabbedPanelContainer(TabbedPanel):
    def __init__(self, **kwargs):
        super(TabbedPanelContainer, self).__init__()

class ChecklistApp(App):
    def __init__(self, *args,**kwargs):
        self.resize_size = 1000
        super(ChecklistApp, self).__init__()

    def build(self):

        root = TabbedPanel(do_default_tab=False)
        root.tab_width = 200
        binary_keys = ["binary_key", "binary", "image_binary_key"]
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
        img.draw_grid()

        tab = TabItem(text="overview",root=root)
        root.add_widget(tab)

        tab = TabItem(text="image",root=root)
        tab.add_widget(img)
        tab.keybindings = img
        root.add_widget(tab)

        tab = TabItem(text="categories",root=root)
        root.add_widget(tab)

        return root

if __name__ == "__main__":
    ChecklistApp().run()    


