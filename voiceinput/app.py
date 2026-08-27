import copy
from collections import deque
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from .config import ConfigStore, PROVIDERS, defaults, ready, validate
from .hotkeys import Hooks, CaptureHooks
from .engine import Session
from .offline import LocalBackend
from . import win32

class App:
    def __init__(self, root, smoke=False):
        self.root, self.smoke = root, smoke
        self.root.title("洛言 · 快捷语音输入")
        self.root.geometry("820x710")
        self.root.minsize(760, 660)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.store = ConfigStore()
        self.load_error = None
        try:
            self.cfg = self.store.load()
        except Exception:
            self.cfg = defaults()
            self.load_error = "配置无法读取，已使用默认值；原文件未覆盖。请检查是否更换了 Windows 账户。"
        self.profiles = copy.deepcopy(self.cfg["profiles"])
        self.events = queue.Queue()
        self.local = LocalBackend()
        self.session = None
        self.target = None
        self.focus_lost = False
        self.pending = deque()
        self.recovered = ""
        self.closing = False
        self.hooks = None
        self.capture_hooks = None
        self.capture_generation = 0
        self.capture_started = 0
        self.tray = None
        self.last_warning = 0
        self.vars = {}
        self.profile_vars = {}
        self._build()
        self._overlay()
        if not smoke:
            self._tray()
            self.install_hooks()
        self.root.after(80, self.poll)
        if self.load_error:
            self.root.after(200, lambda: messagebox.showwarning("配置", self.load_error))
        if smoke:
            self.root.after(1600, self.smoke_report)

    def smoke_report(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Memory(c.Structure):
            _fields_=[("cb",w.DWORD),("faults",w.DWORD)]+[(name,c.c_size_t) for name in
                ("peak_ws","working_set","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
        psapi=c.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.POINTER(Memory),w.DWORD]
        win32.kernel.GetCurrentProcess.restype=w.HANDLE
        info=Memory(cb=c.sizeof(Memory))
        psapi.GetProcessMemoryInfo(win32.kernel.GetCurrentProcess(),c.byref(info),info.cb)
        print(f"Smoke: working_set_mb={info.working_set/1024/1024:.1f}; main_window={self.root.winfo_width()}x{self.root.winfo_height()}",flush=True)
        print("Heavy models imported:",any(name in sys.modules for name in ("faster_whisper","torch","llama_cpp")),flush=True)
        for index in range(4):
            self.notebook.select(index)
            self.root.update_idletasks()
            frame=self.root.nametowidget(self.notebook.tabs()[index])
            clipped=[str(child) for child in frame.winfo_children() if child.winfo_y()+child.winfo_height()>frame.winfo_height() or child.winfo_x()+child.winfo_width()>frame.winfo_width()]
            print(f"Tab {index}: clipped_children={len(clipped)}",flush=True)
        self.quit()

    def _build(self):
        style = ttk.Style()
        style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", padding=(12, 5))
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="洛言  /  快捷语音输入", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="洛阳话 → 普通话书面表达 · 低内存优先", foreground="#64748b").pack(anchor="w", pady=(4,16))
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        general = ttk.Frame(self.notebook, padding=16)
        cloud = ttk.Frame(self.notebook, padding=16)
        offline = ttk.Frame(self.notebook, padding=16)
        about = ttk.Frame(self.notebook, padding=16)
        for frame, name in ((general,"基本设置"),(cloud,"云端接口"),(offline,"离线与资源"),(about,"使用说明")):
            self.notebook.add(frame, text=name)
            frame.columnconfigure(1, weight=1)
        ttk.Label(general,text="快捷键").grid(row=0,column=0,sticky="w",pady=6)
        hotkey_box=ttk.Frame(general)
        hotkey_box.grid(row=0,column=1,sticky="ew",pady=6)
        self.vars["hotkey"]=tk.StringVar(value=self.cfg["hotkey"])
        ttk.Entry(hotkey_box,textvariable=self.vars["hotkey"],state="readonly",width=22).pack(side="left",fill="x",expand=True)
        self.capture_button=ttk.Button(hotkey_box,text="录制快捷键",command=self.begin_capture)
        self.capture_button.pack(side="right",padx=(8,0))
        ttk.Label(general,text="点击录制，再按下并松开键盘组合键 / 鼠标中键、侧键；Esc 取消。",foreground="#64748b",wraplength=680).grid(row=1,column=0,columnspan=2,sticky="w",pady=(0,12))
        self._choices(general,2,"录音方式","trigger",[("按住说话，松开结束","hold"),("按一下开始，再按一下结束","toggle")])
        self._choices(general,3,"文字输入","output",[("停顿后按句输入","sentence"),("结束录音后一次性输入","final")])
        self.vars["offline"] = tk.BooleanVar(value=self.cfg["offline"])
        ttk.Checkbutton(general,text="完全离线（识别和整理都不访问云端）",variable=self.vars["offline"]).grid(row=4,column=0,columnspan=2,sticky="w",pady=14)
        self._field(general,5,"麦克风设备编号（空=系统默认）","microphone")
        ttk.Button(general,text="查看可用麦克风",command=self.devices).grid(row=6,column=1,sticky="w",pady=5)
        ttk.Label(general,text="保存后，将光标放进目标输入框，再使用快捷键。\n窗口或输入控件变化后，结果会暂存，不会强行抢回焦点。\nEsc 可取消录音/处理；取消无法撤回已经输入的文字。",wraplength=690,foreground="#475569").grid(row=7,column=0,columnspan=2,sticky="w",pady=16)
        self.provider = tk.StringVar(value=self.cfg["provider"])
        self.current_profile = self.provider.get()
        ttk.Label(cloud,text="供应商（识别＋整理一起切换）").grid(row=0,column=0,sticky="w",pady=5)
        picker = ttk.Combobox(cloud,textvariable=self.provider,values=list(PROVIDERS),state="readonly")
        picker.grid(row=0,column=1,sticky="ew",pady=5)
        picker.bind("<<ComboboxSelected>>",self.switch_profile)
        labels = [("asr_url","识别接口完整地址"),("asr_model","识别模型 / 引擎"),("app_id","App ID（部分供应商需要）"),
                  ("api_key","ASR Key / SecretId / Token"),("api_secret","ASR Secret / SecretKey"),
                  ("text_url","文字整理接口完整地址"),("text_model","文字整理模型 / 接入点 ID"),("text_key","文字整理 Key / APIPassword")]
        for row,(key,label) in enumerate(labels,1):
            ttk.Label(cloud,text=label).grid(row=row,column=0,sticky="w",padx=(0,12),pady=5)
            var = tk.StringVar(value=self.profiles[self.current_profile][key])
            self.profile_vars[key] = var
            ttk.Entry(cloud,textvariable=var,show="●" if key in ("api_key","api_secret","text_key") else "").grid(row=row,column=1,sticky="ew",pady=5)
        ttk.Label(cloud,text="四家为待实测适配器，需自行开通服务；首次录音会产生 API 调用。\n密钥使用 Windows DPAPI 加密。自定义支持 WAV multipart → {text}，\n文字接口支持 chat/completions 协议，不代表兼容任意 API。",foreground="#64748b",wraplength=690).grid(row=9,column=0,columnspan=2,sticky="w",pady=10)
        rows = [("offline_asr","本地 faster-whisper 模型目录"),("offline_llm","本地文字整理 GGUF 文件"),
                ("offline_device","识别设备（cpu / cuda）"),("idle_seconds","模型闲置卸载（秒）"),
                ("silence_ms","停顿断句时长（毫秒）"),("threshold","声音门限（50–5000）"),
                ("max_segment_s","最长音频分段（3–25 秒）"),("max_record_s","单次最长录音（10–600 秒）")]
        for row,(key,label) in enumerate(rows):
            self._field(offline,row,label,key)
        ttk.Label(offline,text="默认 CPU INT8，模型按需加载；闲置后结束独立进程，释放内存/显存。\n不自动下载模型，不自动回退到云端。文字模型缺失时直接输入原始识别稿。\nCUDA 仅适用于兼容的 NVIDIA 环境；离线洛阳话准确率需实测。",foreground="#64748b",wraplength=690).grid(row=8,column=0,columnspan=2,sticky="w",pady=16)
        instructions = ("1  在云端接口中填写同一家供应商的语音和文字服务参数，点击保存。\n\n"
            "2  打开记事本，把光标放在文本区域，按默认 F8 说话，松开结束。\n\n"
            "3  关闭此窗口会驻留托盘；托盘可打开设置、取回未输入文字或退出。\n\n"
            "低内存：不录音时不采集麦克风；不保存录音、识别历史或正文日志。\n"
            "未输入结果仅保留在内存中，退出后清除；不修改剪贴板。\n\n"
            "按句模式使用本地停顿分段，非逐字流式；讯飞/腾讯/阿里流式接口\n"
            "按实际音频速率发送分段，存在额外等待。后续可优化为持续音频流。\n\n"
            "部分游戏、管理员窗口和特殊控件可能不接受模拟输入。\n"
            "不要在密码框或有选中文本的输入框启动；输入可能替换选中内容。\n"
            "同窗口内网页控件变化不一定能被 Windows 识别，录音时请勿移动光标。")
        ttk.Label(about,text=instructions,wraplength=690,justify="left",foreground="#334155").pack(anchor="nw")
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x",pady=(14,0))
        self.status = tk.StringVar(value="就绪 · 默认 F8 · 尚未调用云端")
        ttk.Label(bottom,textvariable=self.status,wraplength=440).pack(side="left",fill="x",expand=True)
        ttk.Button(bottom,text="保存设置",command=self.save).pack(side="right")
        ttk.Button(bottom,text="隐藏到托盘",command=self.hide).pack(side="right",padx=8)

    def _field(self,frame,row,label,key):
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky="w",padx=(0,12),pady=6)
        variable = tk.StringVar(value=str(self.cfg[key]))
        self.vars[key] = variable
        ttk.Entry(frame,textvariable=variable).grid(row=row,column=1,sticky="ew",pady=6)

    def _choices(self,frame,row,label,key,values):
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky="w",padx=(0,12),pady=8)
        var = tk.StringVar(value=self.cfg[key])
        self.vars[key] = var
        box=ttk.Frame(frame)
        box.grid(row=row,column=1,sticky="w",pady=6)
        for name,value in values:
            ttk.Radiobutton(box,text=name,variable=var,value=value).pack(anchor="w",pady=3)

    def switch_profile(self,event=None):
        self.profiles[self.current_profile].update({k:v.get().strip() for k,v in self.profile_vars.items()})
        self.current_profile=self.provider.get()
        for key,var in self.profile_vars.items():
            var.set(self.profiles[self.current_profile][key])

    def save(self):
        if self.capture_hooks:
            self.status.set("请先完成或取消快捷键录制")
            return
        if self.session or self.pending:
            messagebox.showinfo("稍候","请结束录音并等待输入完成后再修改设置。")
            return
        try:
            cfg=copy.deepcopy(self.cfg)
            for key,var in self.vars.items():
                value=var.get()
                cfg[key]=int(value) if type(self.cfg[key]) is int else value.strip() if isinstance(value,str) else value
            self.switch_profile()
            cfg["profiles"]=copy.deepcopy(self.profiles)
            cfg["provider"]=self.provider.get()
            validate(cfg)
            self.store.save(cfg)
            self.cfg=cfg
            self.install_hooks()
            self.local.unload_idle(0)
            self.status.set("设置已保存 · "+cfg["hotkey"]+" · "+("完全离线" if cfg["offline"] else cfg["provider"]))
        except Exception as exc:
            messagebox.showerror("保存失败",str(exc) if isinstance(exc,ValueError) else "无法保存设置或注册快捷键")

    def install_hooks(self):
        if self.hooks:
            self.hooks.stop()
        self.hooks=Hooks(self.cfg["hotkey"],lambda pressed:self.events.put(("hotkey",(pressed,win32.focus()))))
        self.hooks.start()
        # Escape cancels; it is not swallowed when no recording is active.
        from pynput import keyboard
        if hasattr(self,"escape_hook"):
            self.escape_hook.stop()
        self.escape_hook=keyboard.Listener(on_press=lambda k:self.events.put(("cancel",None)) if k==keyboard.Key.esc else None)
        self.escape_hook.start()

    def begin_capture(self):
        if self.capture_hooks:
            self.finish_capture(None,"已取消快捷键录制")
            return
        if self.session or self.pending:
            self.status.set("请结束语音输入后再录制快捷键")
            return
        self.capture_generation += 1
        generation=self.capture_generation
        self.capture_started=time.monotonic()
        self.capture_target=win32.focus()[0]
        if self.hooks:
            self.hooks.stop()
        if hasattr(self,"escape_hook"):
            self.escape_hook.stop()
        try:
            self.capture_hooks=CaptureHooks(lambda value,error:self.events.put(("captured",(generation,value,error))))
            self.capture_hooks.start()
            self.capture_button.configure(text="取消录制")
            self.status.set("正在录制：请按下并松开快捷键（15 秒内）；不会开始录音")
        except Exception:
            self.finish_capture(None,"快捷键录制启动失败")

    def finish_capture(self,value,error=""):
        if self.capture_hooks:
            self.capture_hooks.stop()
            self.capture_hooks=None
        self.capture_generation += 1
        if value:
            self.vars["hotkey"].set(value)
            self.status.set("已识别："+value+"；点击保存设置后生效")
        else:
            self.status.set(error or "已取消快捷键录制")
        self.capture_button.configure(text="录制快捷键")
        if not self.closing:
            self.install_hooks()

    def _overlay(self):
        self.overlay=tk.Toplevel(self.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost",True)
        self.overlay_label=tk.Label(self.overlay,text="",bg="#172033",fg="white",font=("Microsoft YaHei UI",11),padx=18,pady=10)
        self.overlay_label.pack()
        self.overlay.update_idletasks()
        # Tk creates a native wrapper around the widget window.
        import ctypes
        from ctypes import wintypes
        win32.user.GetParent.argtypes=[wintypes.HWND]
        win32.user.GetParent.restype=wintypes.HWND
        self.overlay_hwnd=win32.user.GetParent(self.overlay.winfo_id()) or self.overlay.winfo_id()
        win32.no_activate(self.overlay_hwnd)
        win32.user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
        self.overlay_timer=None

    def show_status(self,text,temporary=False):
        self.status.set(text)
        self.overlay_label.configure(text=text)
        self.overlay.update_idletasks()
        width=self.overlay.winfo_reqwidth()
        self.overlay.geometry(f"+{max(0,(self.root.winfo_screenwidth()-width)//2)}+{self.root.winfo_screenheight()-150}")
        win32.user.ShowWindow(self.overlay_hwnd,4)  # SW_SHOWNOACTIVATE
        if self.overlay_timer:
            self.root.after_cancel(self.overlay_timer)
            self.overlay_timer=None
        if temporary:
            self.overlay_timer=self.root.after(4500,self.hide_overlay)

    def hide_overlay(self):
        win32.user.ShowWindow(self.overlay_hwnd,0)
        self.overlay_timer=None

    def _tray(self):
        import pystray
        from PIL import Image, ImageDraw
        image=Image.new("RGBA",(64,64),(0,0,0,0))
        draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((4,4,60,60),radius=15,fill="#2563eb")
        draw.rounded_rectangle((25,14,39,39),radius=7,fill="white")
        draw.arc((19,23,45,47),0,180,fill="white",width=3)
        draw.line((32,46,32,53),fill="white",width=3)
        def event(name):
            return lambda icon,item:self.events.put((name,None))
        self.tray=pystray.Icon("LuoyangVoice",image,"洛言 · 快捷语音输入",menu=pystray.Menu(
            pystray.MenuItem("设置",event("settings"),default=True),
            pystray.MenuItem("取回未输入文字",event("recover")),
            pystray.MenuItem("取消当前录音",event("cancel")),
            pystray.MenuItem("退出",event("quit"))))
        self.tray.run_detached()

    def hide(self):
        if self.capture_hooks:
            self.finish_capture(None,"窗口已隐藏，取消快捷键录制")
        self.root.withdraw()

    def devices(self):
        try:
            import sounddevice as sd
            data=sd.query_devices()
            messagebox.showinfo("麦克风", "\n".join(f"{i}: {d['name']}" for i,d in enumerate(data) if d["max_input_channels"]>0) or "未找到输入设备")
        except Exception:
            messagebox.showerror("麦克风","无法枚举设备，请检查音频驱动")

    def hotkey(self,pressed,target):
        if self.capture_hooks:
            return
        if self.session:
            if self.cfg["trigger"]=="toggle" and pressed or self.cfg["trigger"]=="hold" and not pressed:
                self.session.stop()
                self.show_status("处理中…")
            return
        if not pressed:
            return
        if self.pending:
            self.show_status("请等待上一段文字输入完成",True)
            return
        try:
            ready(self.cfg)
            self.target=target
            self.focus_lost=False
            session=Session(self.cfg,self.local,lambda name,data:self.events.put((name,data)))
            session.start()
            self.session=session
            self.show_status("● 录音中 · "+("离线" if self.cfg["offline"] else self.cfg["provider"])+" · Esc 取消")
        except Exception as exc:
            self.session=None
            self.show_status(str(exc) if isinstance(exc,ValueError) else "无法开始录音，请检查麦克风及配置",True)

    def stash(self,text):
        self.recovered += text
        if len(self.recovered)>50000:
            self.recovered=self.recovered[-50000:]
            self.show_status("暂存已达上限，仅保留最近 5 万字",True)

    def recover(self):
        window=tk.Toplevel(self.root)
        window.title("未输入的文字 · 仅在本次运行中暂存")
        window.geometry("680x400")
        area=tk.Text(window,wrap="word",font=("Microsoft YaHei UI",11))
        area.pack(fill="both",expand=True,padx=12,pady=12)
        area.insert("1.0",self.recovered or "暂无未输入文字。")
        ttk.Label(window,text="可选中后手动复制；软件不会自动改写剪贴板。退出后暂存清除。").pack(pady=6)

    def poll(self):
        if self.closing:
            return
        if self.capture_hooks and (time.monotonic()-self.capture_started>15 or win32.focus()[0]!=self.capture_target):
            self.finish_capture(None,"录制超时或窗口已切换，原快捷键不变")
        if (self.session or self.pending) and self.target and win32.focus()!=self.target:
            self.focus_lost=True
        for _ in range(100):
            try:
                name,data=self.events.get_nowait()
            except queue.Empty:
                break
            if name=="captured":
                generation,value,error=data
                if self.capture_hooks and generation==self.capture_generation:
                    self.finish_capture(value,error)
            elif name=="hotkey": self.hotkey(*data)
            elif name=="cancel":
                if self.capture_hooks:
                    self.finish_capture(None,"已取消快捷键录制")
                if self.session:
                    self.session.cancel()
                while self.pending:
                    self.stash(self.pending.popleft()[0])
                if self.session:
                    self.show_status("已取消，等待当前请求结束…",True)
            elif name=="settings":
                self.root.deiconify()
                self.root.lift()
            elif name=="recover": self.recover()
            elif name=="quit":
                self.quit()
                return
            elif name=="text":
                if self.session and self.session.cancel_event.is_set():
                    self.stash(data)
                else:
                    self.pending.append((data,time.monotonic()))
            elif name=="warning":
                self.last_warning=time.monotonic()
                self.show_status(data,True)
            elif name=="status":
                if time.monotonic()-self.last_warning>4:
                    self.show_status(data)
            elif name=="done":
                self.session=None
                if time.monotonic()-self.last_warning>4:
                    self.show_status("处理完成",True)
        if self.pending:
            text,created=self.pending[0]
            if self.focus_lost or time.monotonic()-created>30:
                self.pending.popleft()
                self.stash(text)
                self.show_status("焦点变化或等待超时，文字已暂存到托盘",True)
            elif not win32.modifiers_down():
                self.pending.popleft()
                try:
                    win32.type_text(text,self.target)
                except Exception:
                    self.stash(text)
                    self.show_status("输入未完成，结果已暂存；请检查后手动复制",True)
        self.local.unload_idle(self.cfg["idle_seconds"])
        self.root.after(80,self.poll)

    def quit(self):
        if self.closing:
            return
        self.closing=True
        if self.capture_hooks:
            self.capture_hooks.stop()
        if self.session:
            self.session.cancel()
        if self.hooks:
            self.hooks.stop()
        if hasattr(self,"escape_hook"):
            self.escape_hook.stop()
        self.local.close()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

def run():
    mutex,first=win32.single_instance()
    smoke="--smoke-test" in sys.argv
    root=tk.Tk()
    if not first and not smoke:
        root.withdraw()
        messagebox.showinfo("洛言","程序已经运行，请从系统托盘打开设置。")
        root.destroy()
        return
    app=App(root,smoke=smoke)
    root.mainloop()
