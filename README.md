# 洛言 · Windows 快捷语音输入（首版）

Python + Tkinter 原生设置窗口、托盘、全局键鼠快捷键。默认在线，不加载大模型；录音时才打开麦克风。

**本仓库只提供源码和下载工具，不包含模型权重、虚拟环境、录音或个人配置。使用离线模式请按下方“模型下载地址”自行下载。**

## 本机离线配置与实测（2026-08-28）

以下为开发环境的参考测试，不代表下载本仓库后已安装模型。全新安装默认在线；离线模式需自行下载模型、安装依赖并配置路径。

- 识别目录：`models/faster-whisper-small/`，完整文件约 486 MB。
- 整理文件：`models/qwen/qwen2.5-1.5b-instruct-q4_k_m.gguf`，约 1.12 GB。
- CPU INT8 识别、CPU GGUF 整理，均为 4 线程；文字模型批处理规模已限制。
- 约 5.9 秒本机合成普通话：首次识别约 1.81 秒，复用模型约 0.91 秒。
- 文字整理首次约 1.42 秒，另一短句复用约 0.41 秒（不同句子不应直接当成同条件速度对比）。
- 识别模型进程工作集约 401 MB；两模型同时加载约 2119 MB。不是 40 MB 的空闲主程序占用。
- 完整处理流程无警告、闲置卸载验证通过，测试结束的模型进程已退出。
- 51 项自动化测试通过，`pip check` 无依赖冲突。

复现测试后会在本地生成 `test-artifacts/offline-test.json`（报告和音频不上传仓库）。这是合成普通话与口语文本整理测试，**不是本人洛阳话录音的准确率测试，也未代替真实键鼠和目标输入框的手动验收**。

## 启动

在 Windows 安装 Python（建议使用已测试的 3.10），下载或克隆本仓库，双击 `install.cmd` 安装依赖，再双击 `start.cmd`。仓库不包含 `.venv`。

1. 打开「云端接口」，选供应商，填写已开通服务对应的密钥与模型。
2. 点击「保存设置」，关闭窗口使其隐藏到系统托盘。
3. 在记事本文本区域放置光标，默认 **按住 F8 说话，松开结束**。
4. 托盘可打开设置、取回未输入文字、取消录音或退出。

### 快捷键自动识别

在「基本设置」点击 **录制快捷键**，直接按下并松开需要的键盘组合键、鼠标中键或侧键。
程序自动识别并填入，不需要手输 `ctrl+alt+v` 等名称。再点「保存设置」生效。

- 录制快捷键期间暂停语音快捷键，不会同时开始录音。
- 支持 Ctrl / Alt / Shift / Win 与主键、鼠标中键/侧键组合；单个字母数字必须搭配 Ctrl / Alt / Win。
- 松开所有组合键后确认；Esc、再次点击按钮、切换窗口或等待 15 秒可取消，原设置不变。
- 鼠标左键、右键不作为语音快捷键，以保留界面正常点击。

不自动创建账号、不自动购买服务、不自动调用 API 测试。**使用在线模式录音会将音频和识别文字发送到所选服务，可能产生费用**。

## 已实现

- 按住说话 / 单击开始与结束。
- 停顿后按句输入 / 录音结束后一次性输入。
- F1–F24、带修饰键的字母数字、中键、侧键；如 `f8`、`ctrl+alt+v`、`mouse_x1`。
- 消耗选定快捷键的主键事件，避免鼠标侧键同时触发浏览器后退；不全局屏蔽其他按键。
- 同一供应商配置内同时保存识别模型与文字整理模型，随供应商一起切换。
- 洛阳话识别稿转普通话书面表达的整理提示词；整理失败时输入原文。
- Windows Unicode SendInput 输入，不占用或更改剪贴板。
- 可检测的窗口/原生输入控件焦点变化时暂存结果；不抢回焦点。
- Esc 取消当前录音与后续输入；已发送的云端请求可能仍完成计费，已输入内容不会撤回。
- 麦克风选择、断句门限、最长分段、录音时长限制。
- 原始录音不落盘，无识别历史或正文日志；未输入结果只在进程内暂存（最多 5 万字）。
- 密钥采用 Windows DPAPI 加密，配置在 `%LOCALAPPDATA%\LuoyangVoice\settings.json`。
- 单实例；退出后停止钩子、录音和离线进程。

## 四家候选的配置

以下为**依据文档编写、通过模拟协议测试、尚未使用真实密钥联调**的适配器。模型名、权限、地域必须与自己的控制台一致。

| 供应商 | ASR 配置 | 同厂商文字整理配置 |
| --- | --- | --- |
| 讯飞 | 方言大模型，App ID / API Key / API Secret，默认 `slm` | 星火 HTTP，单独填写 APIPassword，默认 `lite`，按已开通版本修改 |
| 阿里云 | 百炼 API Key，默认 `fun-asr-realtime`；默认中国内地地址 | 百炼文字模型及 API Key，可与 ASR 填相同 Key，前提是都已授权 |
| 腾讯云 | App ID / SecretId / SecretKey，默认 `16k_zh_large` | 混元兼容接口的 API Key（不是 ASR SecretKey），按控制台模型调整 |
| 火山引擎 | 极速版识别，新版填 ASR Key；旧版填 App ID + Access Token | 方舟 API Key + 模型名或接入点 ID；模型默认留空，需按控制台填写 |

接口地址均为**完整调用地址**，不是只填写域名。必须使用 HTTPS / WSS；不会自动跟随 HTTP 重定向。

自定义接口限定为：识别 POST multipart，`file` 为 WAV、`model` 为模型名，Bearer 鉴权，响应 `{"text":"识别结果"}`；文字整理为 `chat/completions` 风格请求。任意厂商特有协议需新增适配器，不是仅换 URL 就能兼容。

官方参考：

- [讯飞方言大模型](https://www.xfyun.cn/doc/spark/spark_slm_iat.html)
- [讯飞星火 HTTP](https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html)
- [阿里云 ASR 客户端事件](https://help.aliyun.com/zh/model-studio/fun-asr-client-events)
- [阿里云 ASR 服务端事件](https://help.aliyun.com/zh/model-studio/fun-asr-server-events)
- [腾讯实时识别](https://cloud.tencent.com/document/api/1093/48982)
- [腾讯混元兼容接口](https://cloud.tencent.com/document/product/1729/111007)
- [火山录音文件极速版](https://www.volcengine.com/docs/6561/1631584?lang=zh)

## 离线模式：可选安装，不预加载

双击 `install-offline.cmd` 安装离线运行库（使用上游预编译 CPU wheel）。**该安装脚本不下载模型**，模型由使用者自行下载。

### 模型下载地址

**1. 语音识别：Systran/faster-whisper-small（约 486 MB）**

- [Hugging Face 下载](https://huggingface.co/Systran/faster-whisper-small/tree/main)
- [ModelScope 国内下载](https://modelscope.cn/models/Systran/faster-whisper-small/files)
- 下载 `model.bin`、`config.json`、`tokenizer.json`、`vocabulary.txt`，放在同一个目录。
- 建议目录：项目下 `models/faster-whisper-small/`；不要选择 `.en` 纯英文版本。

**2. 文字整理：Qwen2.5-1.5B-Instruct-GGUF（Q4_K_M，约 1.12 GB）**

- [Qwen 官方 Hugging Face 下载](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/main)
- [Qwen 官方 ModelScope 国内下载](https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/files)
- 只下载 `qwen2.5-1.5b-instruct-q4_k_m.gguf`，无需下载其他量化版本。
- 建议放在项目下 `models/qwen/`。

下载后在软件的「离线与资源」中分别填写识别模型目录、GGUF 文件完整路径；在「基本设置」勾选“完全离线”，保存后使用。模型的下载体积不等于运行内存，使用时请遵守各模型发布者的许可证。

### 可选：手动运行下载工具

不想逐个下载文件，可由使用者主动执行以下命令。脚本支持断点续传和大文件 SHA256 校验：

```bat
.venv\Scripts\python.exe download_models.py --modelscope
```

国内源会先比对大文件与 Hugging Face 原发布者的 SHA256，再续传；不会混用不同版本权重。

已安装运行库后，可运行真实离线测试（合成普通话，不采集麦克风、不调用云端）：

```bat
.venv\Scripts\python.exe -m pip install comtypes
.venv\Scripts\python.exe local_model_test.py --configure
```

脚本用 Windows 本机慧慧声音合成测试句，测试识别、整理、重复推理与闲置卸载。
只有测试成功才写入模型路径并开启离线模式；保留现有 API 密钥、快捷键等配置。
结果在 `test-artifacts/offline-test.json`，音频是公开测试句的本机合成，不是用户录音。
正在运行的旧版程序需要先退出再重新启动，才会读取新代码与配置。

提供本地 `faster-whisper` 识别和 `llama-cpp-python` GGUF 文字整理后端。`models/` 与 `test-artifacts/` 仅由使用者在本地生成，已被 Git 忽略。**合成普通话测试不代表洛阳方言识别准确率，方言仍需实测**。

```bat
.venv\Scripts\python.exe -m pip install -r requirements-offline.txt
```

`llama-cpp-python` 在部分 Windows 环境需额外的 C++ 构建工具或匹配的预编译 wheel，参见官方安装文档。不要为了试用在线模式安装这些大型依赖。

- 预先准备兼容 faster-whisper 的本地模型目录，填入「离线与资源」。不支持直接填一个 PyTorch `.pt` 文件。
- 准备支持聊天模板的指令模型 GGUF 文件作为书面化整理模型。未配置或整理失败，回退为原始识别稿。
- 默认识别 CPU INT8、4 线程，文字模型 CPU，避免假设独显是 NVIDIA。
- 识别稿可能来自模型的繁体输出，通过本地 OpenCC 转为简体，不需要联网，也不依赖文字模型成功。
- 仅在兼容 NVIDIA CUDA/cuDNN 环境中选择 `cuda`。当前未确认本机显卡型号。
- 模型在首次任务时加载到独立进程，闲置默认 60 秒后终止进程，释放模型内存与显存。可设为 5 秒以更积极释放，但下次启动更慢。
- 离线任务不会调用云端 API。代码禁用模型自动联网下载，不会在失败时改用云端。

参考：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[llama-cpp-python](https://github.com/abetlen/llama-cpp-python)。

## 资源与当前限制

- 本机一次启动测试：**约 40 MB 工作集**，设置窗口开启，未加载离线模型、未录音。此数字不代表录音中、模型运行时或其他机器上的内存占用。
- 16 kHz、16-bit、单声道 PCM；采集队列最多 5 秒，识别队列最多 8 段，默认每段最多 15 秒。队列满或音频溢出会停止录音并提示，不会无限积压。
- 默认单次录音上限 300 秒，可设 10–600 秒。
- **按句输入不等于逐字实时流式输入**：当前先本地能量门限断句，再识别/整理；讯飞、腾讯、阿里需要按实时速率回放分段，故额外延迟可能接近段长。持续流式低延迟优化尚未完成。火山使用 HTTP 极速版分段识别。
- 能量门限不是神经网络 VAD，嘈杂环境可能误断句；连续说话达到段长上限会强制切段，可能影响词句边界。
- 停止录音只停止采集，仍会处理已排队音频；网络慢时可 Esc 取消。
- 焦点检测以 Windows 窗口/原生控件为粒度，浏览器同窗口不同输入框、同控件光标移动未必能检测。录音和输入过程中不要切换位置，不要在密码框使用。
- 不保证支持管理员程序、游戏、受保护控件；失败时从托盘取回文字。部分输入失败时可能已有部分文字，请核对后复制，避免重复。
- 首版没有 EXE 打包、自动更新、开机自启；不改系统安全设置。
- Windows 截图接口在本机返回 `SetIsBorderRequired ... 0x80004002`，因此仅完成启动、控件边界与辅助功能树检查，未完成截图视觉验收。

## 测试

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe main.py --smoke-test
```

测试不打开麦克风、不发送云端请求。覆盖快捷键状态、音频分段、DPAPI、配置保存、协议解析、整理失败回退、两种输入时机、取消和离线不调用云端。

真实验收建议：用同一组洛阳话录音，分别测试四家候选的错字、地名人名、方言与普通话混说、延迟和计费；在普通记事本中验证实际按键、麦克风、输入与焦点切换。首次可先选一家完成闭环。
