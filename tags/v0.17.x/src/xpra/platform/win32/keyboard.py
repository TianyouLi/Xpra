# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

import win32api         #@UnresolvedImport
import win32con         #@UnresolvedImport
import win32gui         #@UnresolvedImport

from xpra.platform.keyboard_base import KeyboardBase
from xpra.keyboard.layouts import WIN32_LAYOUTS
from xpra.gtk_common.keymap import KEY_TRANSLATIONS
from xpra.log import Logger
log = Logger("keyboard")

EMULATE_ALTGR = os.environ.get("XPRA_EMULATE_ALTGR", "1")=="1"
EMULATE_ALTGR_CONTROL_KEY_DELAY = int(os.environ.get("XPRA_EMULATE_ALTGR_CONTROL_KEY_DELAY", "50"))
if EMULATE_ALTGR:
    #needed for altgr emulation timeouts:
    from xpra.gtk_common.gobject_compat import import_glib
    glib = import_glib()


class Keyboard(KeyboardBase):
    """ This is for getting keys from the keyboard on the client side.
        Deals with GTK bugs and oddities:
        * missing 'Num_Lock'
        * simulate 'Alt_Gr'
    """

    def __init__(self):
        KeyboardBase.__init__(self)
        self.num_lock_modifier = None
        self.altgr_modifier = None
        self.delayed_event = None
        #workaround for "period" vs "KP_Decimal" with gtk2 (see ticket #586):
        #translate "period" with keyval=46 and keycode=110 to KP_Decimal:
        KEY_TRANSLATIONS[("period",     46,     110)]   = "KP_Decimal"
        #workaround for "fr" keyboards, which use a different key name under X11:
        KEY_TRANSLATIONS[("dead_tilde", 65107,  50)]    = "asciitilde"
        KEY_TRANSLATIONS[("dead_grave", 65104,  55)]    = "grave"

    def set_modifier_mappings(self, mappings):
        KeyboardBase.set_modifier_mappings(self, mappings)
        self.num_lock_modifier = self.modifier_keys.get("Num_Lock")
        log("set_modifier_mappings found 'Num_Lock' with modifier value: %s", self.num_lock_modifier)
        for x in ("ISO_Level3_Shift", "Mode_switch"):
            mod = self.modifier_keys.get(x)
            if mod:
                self.altgr_modifier = mod
                log("set_modifier_mappings found 'AltGr'='%s' with modifier value: %s", x, self.altgr_modifier)
                break

    def mask_to_names(self, mask):
        """ Patch NUMLOCK and AltGr """
        names = KeyboardBase.mask_to_names(self, mask)
        altgr = win32api.GetKeyState(win32con.VK_RMENU) not in (0, 1)
        if altgr:
            self.AltGr_modifiers(names)
        if self.num_lock_modifier:
            try:
                numlock = win32api.GetKeyState(win32con.VK_NUMLOCK)
                if numlock and self.num_lock_modifier not in names:
                    names.append(self.num_lock_modifier)
                elif not numlock and self.num_lock_modifier in names:
                    names.remove(self.num_lock_modifier)
                log("mask_to_names(%s) GetKeyState(VK_NUMLOCK)=%s, names=%s", mask, numlock, names)
            except:
                pass
        else:
            log("mask_to_names(%s)=%s", mask, names)
        return names

    def AltGr_modifiers(self, modifiers, pressed=True):
        add = []
        clear = ["mod1", "mod2", "control"]
        if self.altgr_modifier:
            if pressed:
                add.append(self.altgr_modifier)
            else:
                clear.append(self.altgr_modifier)
        log("AltGr_modifiers(%s, %s) AltGr=%s, add=%s, clear=%s", modifiers, pressed, self.altgr_modifier, add, clear)
        for x in add:
            if x not in modifiers:
                modifiers.append(x)
        for x in clear:
            if x in modifiers:
                modifiers.remove(x)

    def get_keymap_modifiers(self):
        """
            ask the server to manage numlock, and lock can be missing from mouse events
            (or maybe this is virtualbox causing it?)
        """
        return  {}, [], ["lock"]

    def get_layout_spec(self):
        layout = None
        layouts = []
        variant = None
        variants = None
        try:
            kbid = win32api.GetKeyboardLayout(0) & 0xffff
            if kbid in WIN32_LAYOUTS:
                code, _, _, _, layout, variants = WIN32_LAYOUTS.get(kbid)
                log("found keyboard layout '%s' with variants=%s, code '%s' for kbid=%s", layout, variants, code, kbid)
            if not layout:
                log("unknown keyboard layout for kbid: %s", kbid)
            else:
                layouts.append(layout)
        except Exception as e:
            log.error("failed to detect keyboard layout: %s", e)
        return layout,layouts,variant,variants

    def get_keyboard_repeat(self):
        try:
            _delay = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDDELAY)
            _speed = win32gui.SystemParametersInfo(win32con.SPI_GETKEYBOARDSPEED)
            #now we need to normalize those weird win32 values:
            #0=250, 3=1000:
            delay = (_delay+1) * 250
            #0=1000/30, 31=1000/2.5
            _speed = min(31, max(0, _speed))
            speed = int(1000/(2.5+27.5*_speed/31))
            log("keyboard repeat speed(%s)=%s, delay(%s)=%s", _speed, speed, _delay, delay)
            return  delay,speed
        except Exception as e:
            log.error("failed to get keyboard rate: %s", e)
        return None


    def process_key_event(self, send_key_action_cb, wid, key_event):
        """ Caps_Lock and Num_Lock don't work properly: they get reported more than once,
            they are reported as not pressed when the key is down, etc
            So we just ignore those and rely on the list of "modifiers" passed
            with each keypress to let the server set them for us when needed.
        """
        if key_event.keyval==2**24-1 and key_event.keyname=="VoidSymbol":
            return
        #self.modifier_mappings = None       #{'control': [(37, 'Control_L'), (105, 'Control_R')], 'mod1':
        #self.modifier_keys = {}             #{"Control_L" : "control", ...}
        #self.modifier_keycodes = {}         #{"Control_R" : [105], ...}
        #self.modifier_keycodes = {"ISO_Level3_Shift": [108]}
        #we can only deal with 'Alt_R' and simulate AltGr (ISO_Level3_Shift)
        #if we have modifier_mappings
        if EMULATE_ALTGR and self.altgr_modifier and len(self.modifier_mappings)>0:
            altgr = win32api.GetKeyState(win32con.VK_RMENU) not in (0, 1)
            if key_event.keyname=="Control_L":
                log("process_key_event: Control_L pressed=%s, with altgr=%s", key_event.pressed, altgr)
                #AltGr is often preceded by a spurious "Control_L" event
                #delay this one a little bit so we can skip it if an "AltGr" does come through next:
                if key_event.pressed:
                    if not altgr:
                        self.delayed_event = (send_key_action_cb, wid, key_event)
                        glib.timeout_add(EMULATE_ALTGR_CONTROL_KEY_DELAY, self.send_delayed_key)
                    return
                if not key_event.pressed and altgr:
                    #unpressed: could just skip it?
                    #(but maybe the real one got pressed.. and this would get it stuck)
                    pass
            if key_event.keyname=="Alt_R":
                log("process_key_event: Alt_R pressed=%s, with altgr=%s", key_event.pressed, altgr)
                if altgr and key_event.pressed:
                    #cancel "Control_L" if one was due:
                    self.delayed_event = None
                #modify the key event so that it will only trigger the modifier update,
                #and not not the key event itself:
                key_event.string = ""
                key_event.keyname = ""
                key_event.group = -1
                key_event.keyval = -1
                key_event.keycode = -1
                self.AltGr_modifiers(key_event.modifiers)
        self.send_delayed_key()
        KeyboardBase.process_key_event(self, send_key_action_cb, wid, key_event)

    def send_delayed_key(self):
        #timeout: this must be a real one, send it now
        dk = self.delayed_event
        log("send_delayed_key() delayed_event=%s", dk)
        if dk:
            self.delayed_event = None
            altgr = win32api.GetKeyState(win32con.VK_RMENU) not in (0, 1)
            if altgr:
                KeyboardBase.process_key_event(self, *dk)