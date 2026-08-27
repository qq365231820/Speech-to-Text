import re
import threading

MODIFIERS = {"ctrl", "alt", "shift", "win"}
MOUSE = {"mouse_middle", "mouse_x1", "mouse_x2"}
MODIFIER_VKS = {0x10:"shift",0xa0:"shift",0xa1:"shift",0x11:"ctrl",0xa2:"ctrl",0xa3:"ctrl",
                0x12:"alt",0xa4:"alt",0xa5:"alt",0x5b:"win",0x5c:"win"}

def key_from_vk(vk):
    if vk in MODIFIER_VKS:
        return MODIFIER_VKS[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5a:
        return chr(vk).lower()
    if 0x70 <= vk <= 0x87:
        return f"f{vk-0x6f}"
    return {0x20:"space",0x13:"pause",0x91:"scroll_lock",0x2d:"insert",0x1b:"esc"}.get(vk, "unsupported")

class CaptureState:
    """Commit a chord only after its keys are released; never records typed text."""
    def __init__(self, callback):
        self.callback = callback
        self.down = {}
        self.candidate = None
        self.error = ""
        self.finished = False
        self.lock = threading.Lock()

    def feed(self, physical, name, pressed):
        with self.lock:
            if self.finished:
                return
            if pressed:
                if physical in self.down:
                    return
                self.down[physical] = name
                if name == "esc":
                    self.candidate = ""
                    self.error = "已取消快捷键录制"
                elif name not in MODIFIERS and self.candidate is None:
                    modifiers = [key for key in ("ctrl", "alt", "shift", "win") if key in self.down.values()]
                    self.candidate = "+".join(modifiers+[name])
                    try:
                        parse_hotkey(self.candidate)
                    except ValueError as exc:
                        self.error = str(exc)
            else:
                self.down.pop(physical, None)
                if not self.down:
                    if self.candidate is None:
                        return  # Modifier alone: continue waiting for a main key.
                    self.finished = True
                    self.callback(None if self.error else self.candidate, self.error)

class CaptureHooks:
    def __init__(self, callback):
        from pynput import keyboard, mouse
        self.state = CaptureState(callback)
        def keyboard_filter(msg, data):
            if msg not in (0x100,0x101,0x104,0x105) or data.vkCode == 0xe7:
                return False
            self.state.feed(data.vkCode, key_from_vk(data.vkCode), msg in (0x100,0x104))
            self.keyboard.suppress_event()
        def mouse_filter(msg, data):
            if msg in (0x207,0x208):
                self.state.feed("mouse_middle","mouse_middle",msg==0x207)
                self.mouse.suppress_event()
            elif msg in (0x20b,0x20c):
                name="mouse_x1" if data.mouseData>>16==1 else "mouse_x2"
                self.state.feed(name,name,msg==0x20b)
                self.mouse.suppress_event()
            return False
        self.keyboard = keyboard.Listener(win32_event_filter=keyboard_filter)
        self.mouse = mouse.Listener(win32_event_filter=mouse_filter)

    def start(self):
        self.keyboard.start()
        self.mouse.start()

    def stop(self):
        self.keyboard.stop()
        self.mouse.stop()

def parse_hotkey(value):
    tokens = value.lower().replace(" ", "").split("+")
    if not tokens or len(set(tokens)) != len(tokens):
        raise ValueError("快捷键格式错误")
    main = [t for t in tokens if t not in MODIFIERS]
    if len(main) != 1:
        raise ValueError("快捷键需要一个主键，例如 f8、ctrl+alt+v、mouse_x1")
    key = main[0]
    if not (key in MOUSE or re.fullmatch(r"f(?:[1-9]|1[0-9]|2[0-4])", key) or
            (len(key) == 1 and key.isascii() and key.isalnum()) or key in {"space", "pause", "scroll_lock", "insert"}):
        raise ValueError("不支持该按键；可用 F1–F24、字母数字、中键或侧键")
    if len(key) == 1 and not (set(tokens) & {"ctrl", "alt", "win"}):
        raise ValueError("字母数字快捷键必须带 Ctrl、Alt 或 Win，避免影响打字")
    return frozenset(tokens)

class ChordState:
    def __init__(self, chord, callback):
        self.chord, self.callback = parse_hotkey(chord), callback
        self.down = set()
        self.active = False
        self.lock = threading.Lock()

    def feed(self, key, pressed):
        with self.lock:
            self._feed(key, pressed)

    def _feed(self, key, pressed):
        if pressed:
            self.down.add(key)
        else:
            self.down.discard(key)
        active = self.chord <= self.down
        if active != self.active:
            self.active = active
            self.callback(active)

class Hooks:
    def __init__(self, chord, callback):
        from pynput import keyboard, mouse
        self.state = ChordState(chord, callback)
        self.primary = next(t for t in self.state.chord if t not in MODIFIERS)
        self.modifiers = self.state.chord & MODIFIERS
        self.suppressed = set()
        self.physical_modifiers = set()
        modifier_vks = MODIFIER_VKS
        def dispatch(key, pressed, listener):
            swallow = key in self.suppressed or (key == self.primary and pressed and self.modifiers <= self.state.down)
            self.state.feed(key, pressed)
            if swallow:
                if pressed: self.suppressed.add(key)
                else: self.suppressed.discard(key)
                listener.suppress_event()
        def keyboard_filter(msg, data):
            # Ignore Unicode packets from our own text insertion.
            vk = data.vkCode
            if vk == 0xe7 or msg not in (0x100,0x101,0x104,0x105):
                return False
            pressed = msg in (0x100,0x104)
            if vk in modifier_vks:
                if pressed: self.physical_modifiers.add(vk)
                else: self.physical_modifiers.discard(vk)
                name = modifier_vks[vk]
                self.state.feed(name,any(modifier_vks[v]==name for v in self.physical_modifiers))
            else:
                name = key_from_vk(vk)
                if name: dispatch(name,pressed,self.keyboard)
            return False
        def mouse_filter(msg,data):
            if msg in (0x207,0x208):
                dispatch("mouse_middle",msg==0x207,self.mouse)
            elif msg in (0x20b,0x20c):
                dispatch("mouse_x1" if data.mouseData>>16==1 else "mouse_x2",msg==0x20b,self.mouse)
            return False
        self.keyboard = keyboard.Listener(win32_event_filter=keyboard_filter)
        self.mouse = mouse.Listener(win32_event_filter=mouse_filter)

    def start(self):
        self.keyboard.start()
        self.mouse.start()

    def stop(self):
        self.keyboard.stop()
        self.mouse.stop()
