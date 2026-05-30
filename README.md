# Moist Canvas

Moist Canvas 是一个本地运行的 AI 无限画布。它通过在线 API 服务生成和编辑图片 / 视频，不需要本地 GPU，也不需要安装 ComfyUI。

## 普通用户使用方法（Windows 64 位）

1. 先完整解压整个 ZIP，不要在压缩包预览窗口里直接运行。
2. 双击 `安装依赖.bat`。
3. 等待脚本自动下载便携 Python，并安装项目依赖。
4. 安装完成后，双击 `运行文件.bat`。
5. 浏览器会自动打开 `http://127.0.0.1:6767/`。
6. 第一次使用时，在网页里的 API 设置页面填写自己的 API Key。

第一次安装需要联网。用户不需要自己安装 Python。

## 运行要求

- Windows 64 位系统。
- 第一次安装时需要联网，用来下载便携 Python 和 Python 依赖库。
- 需要浏览器，Windows 自带 Edge 即可。
- 生成图片 / 视频时需要可用的 API Key，例如 APIMart、ModelScope 或 OpenAI 兼容服务。

项目不需要：

- 本地 GPU
- ComfyUI
- Node.js / npm
- 数据库

## 本地数据说明

这些目录和文件是本机运行时产生的，不应该发给别人：

- `API/.env`：本地 API Key / 环境变量。
- `runtime/`：`安装依赖.bat` 自动下载的便携 Python 和依赖。
- `output/`：生成的图片 / 视频。
- `history.json`：生成历史索引。
- `data/canvases_v2/`：画布存档。
- `data/*_cache.json`：模型列表、汇率等缓存。
- `*.log`：本地运行日志。

## 生成可分享的纯净 ZIP

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_clean_zip.ps1
```

生成结果：

```text
dist\MoistCanvas-Clean.zip
```

这个 ZIP 是给别人使用的纯净包。它只包含程序文件、静态资源、默认 API 服务配置、安装脚本和运行脚本，不包含你的 API Key、历史记录、生成内容、缓存、日志或便携 Python。

收到 ZIP 的用户解压后，先运行 `安装依赖.bat`，再运行 `运行文件.bat`。

## 开发者运行方式

如果你已经安装了 Python 3.10+，也可以直接在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

然后打开：

```text
http://127.0.0.1:6767/
```
