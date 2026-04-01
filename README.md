# SCDZJXZYJSXY-campus_auth

针对四川电子机械职业技术学院的校园宽带，实现全自动登录。支持单次认证、失败自动重试、断线自动重连。

技术难点在于认证页面部署了重度混淆的反爬 JS，且服务端通过 Java URL Rewriting（而非 Cookie）传递 JSESSIONID，导致常规自动化方案失效。最终方案通过 Playwright 原样透传反爬 JS，从 Frame URL 路径段提取 JSESSIONID，完整还原浏览器认证流程。

## 环境要求

- Python 3.11
- Windows（其他平台理论可用，路径需自行调整）

## 安装

```bash
pip install "playwright==1.58.0" "ddddocr==1.4.11" "numpy<2" "onnxruntime==1.16.3"
playwright install chromium
```

## 使用

**首次运行**会提示输入学号和密码，保存到本地 `config.json` 后不再询问。

```bash
# 单次认证
py -3.11 campus_auth.py

# 断线自动重连（每 30 秒检测一次，Ctrl+C 退出）
py -3.11 campus_auth.py --watch

# 重置保存的账号密码
py -3.11 campus_auth.py --reset
```

## 打包为 exe

```bash
pip install pyinstaller
py -3.11 -m PyInstaller auth.spec
```

打包结果在 `dist\campus_auth\` 文件夹，将整个文件夹分发给他人即可，无需安装 Python。

> 打包前确认已运行 `playwright install chromium`，并根据实际 Chromium 路径修改 `auth.spec` 中的 `chromium_src` 变量。

## 注意事项

- `config.json` 明文存储账号密码，请勿将其上传到公开仓库
- 本项目仅供学习交流，请遵守学校相关规定

## 技术栈

- [Playwright](https://playwright.dev/python/) — 浏览器自动化
- [ddddocr](https://github.com/sml2h3/ddddocr) — 验证码识别
- [PyInstaller](https://pyinstaller.org/) — 打包为可执行文件

## License

MIT
