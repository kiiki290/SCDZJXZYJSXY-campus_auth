"""
校园宽带自动认证 CLI 版
用法：
    py -3.11 campus_auth.py              # 单次认证
    py -3.11 campus_auth.py --watch      # 断线自动重连模式
    py -3.11 campus_auth.py --reset      # 重置保存的账号密码
"""

import asyncio
import re
import random
import sys
import time
import json
import os
import argparse
from datetime import datetime

import ddddocr
from playwright.async_api import async_playwright

# ── 常量 ──────────────────────────────────────────────────────────────────────
PORTAL        = "http://218.200.239.185:8888/portalserver"
BRAS_IP       = "221.182.124.4"
ANTIBOT       = re.compile(r"4QbVtADbnLVIc|\.a5bda9d\.", re.IGNORECASE)
CONFIG_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
POLL_INTERVAL = 15   # 断线检测间隔（秒）
MAX_RETRY     = 3    # 单次认证最大重试次数


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_config() -> dict | None:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_config(student_id: str, password: str):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"student_id": student_id, "password": password}, f, ensure_ascii=False)
    log(f"账号密码已保存到 {CONFIG_FILE}")


def prompt_credentials() -> tuple[str, str]:
    print("首次使用，请输入账号密码（将保存到本地）：")
    sid = input("账号: ").strip()
    pwd = input("密码: ").strip()
    save_config(sid, pwd)
    return sid, pwd


# ── 检测是否在线 ───────────────────────────────────────────────────────────────
async def is_offline(context) -> bool:
    try:
        r = await context.request.get("http://1.1.1.1", max_redirects=0, timeout=6000)
        loc = r.headers.get("location", "")
    except Exception as e:
        loc = str(e)
    return "wlanuserip=" in loc


# ── 认证核心 ──────────────────────────────────────────────────────────────────
async def do_auth(student_id: str, password: str) -> bool:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        async def intercept(route, request):
            try:
                if ANTIBOT.search(request.url):
                    resp = await context.request.fetch(request)
                    await route.fulfill(response=resp)
                else:
                    await route.continue_()
            except Exception:
                pass

        page = await context.new_page()
        await page.route("**/*", intercept)

        # 1. WAN IP
        log("获取 WAN IP ...")
        try:
            r = await context.request.get("http://1.1.1.1", max_redirects=0, timeout=6000)
            loc = r.headers.get("location", "")
        except Exception as e:
            loc = str(e)
        m = re.search(r"wlanuserip=(\d+\.\d+\.\d+\.\d+)", loc)
        wan_ip = m.group(1) if m else None
        if not wan_ip:
            log("  无法获取 WAN IP（可能已在线）")
            await browser.close()
            return False
        log(f"  WAN IP = {wan_ip}")

        # 2. 加载认证页面
        log("加载认证页面 ...")
        outer = f"{PORTAL}/scunioncmccgxsd44.jsp?wlanuserip={wan_ip}&wlanacname="
        await page.goto(outer, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(5000)

        if len(page.frames) < 2:
            log("  找不到认证 Frame")
            await browser.close()
            return False

        auth_frame = page.frames[1]
        content = await auth_frame.content()
        if content.strip() == "<html><head></head><body></body></html>":
            log("  Frame 渲染为空白")
            await browser.close()
            return False
        log("  认证页面加载成功")

        # 3. 验证码
        log("识别验证码 ...")
        jsid_match = re.search(r"jsessionid=([A-F0-9]+)", auth_frame.url, re.IGNORECASE)
        jsessionid = jsid_match.group(1) if jsid_match else ""

        captcha_code = None
        for attempt in range(1, 4):
            cap_url = (
                f"{PORTAL}/user/randomimage"
                + (f";jsessionid={jsessionid}" if jsessionid else "")
                + f"?id={random.randint(100000, 999999)}"
            )
            cap_resp = await context.request.get(cap_url)
            if "image" not in cap_resp.headers.get("content-type", ""):
                log(f"  第 {attempt} 次验证码获取失败，重试 ...")
                await asyncio.sleep(1)
                continue
            img_bytes = await cap_resp.body()
            ocr = ddddocr.DdddOcr(show_ad=False)
            captcha_code = ocr.classification(img_bytes).strip().replace(" ", "")
            log(f"  第 {attempt} 次识别：{captcha_code}")
            if len(captcha_code) >= 4:
                break
            captcha_code = None

        if not captcha_code:
            log("  验证码识别失败")
            await browser.close()
            return False

        # 4. 提交
        log("提交登录表单 ...")
        await auth_frame.fill("#username", student_id)
        await auth_frame.fill("#pwd", password)
        await auth_frame.fill("#ps", captcha_code)

        async with page.expect_response(
            lambda r: "unionautologin.do" in r.url and r.request.method == "POST",
            timeout=20000
        ) as resp_info:
            await auth_frame.evaluate(f"""
                var f = document.querySelector('form');
                if ('{jsessionid}' && !f.action.includes('jsessionid')) {{
                    f.action = f.action.replace(
                        'unionautologin.do',
                        'unionautologin.do;jsessionid={jsessionid}'
                    );
                }}
                f.submit();
            """)

        resp = await resp_info.value
        text = await resp.text()
        ok = "登录成功" in text or any(k in text for k in ["success", "logout", "online"])
        log("OK 认证成功！" if ok else "FAIL 认证失败")

        await browser.close()
        return ok


# ── 单次认证（带重试）────────────────────────────────────────────────────────
def auth_with_retry(student_id: str, password: str) -> bool:
    for attempt in range(1, MAX_RETRY + 1):
        if attempt > 1:
            log(f"第 {attempt} 次尝试 ...")
        try:
            result = asyncio.run(do_auth(student_id, password))
        except Exception as e:
            log(f"异常：{e}")
            result = False
        if result:
            return True
        if attempt < MAX_RETRY:
            log("5 秒后重试 ...")
            time.sleep(5)
    return False


# ── 断线监控模式 ──────────────────────────────────────────────────────────────
async def _check_offline():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        result = await is_offline(context)
        await browser.close()
        return result


def watch_mode(student_id: str, password: str):
    log(f"进入断线监控模式（每 {POLL_INTERVAL} 秒检测一次），Ctrl+C 退出")
    while True:
        try:
            offline = asyncio.run(_check_offline())
            if offline:
                log("检测到断线，开始认证 ...")
                auth_with_retry(student_id, password)
            else:
                log("在线 OK")
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("已退出监控模式")
            break
        except Exception as e:
            log(f"监控异常：{e}，{POLL_INTERVAL} 秒后重试")
            time.sleep(POLL_INTERVAL)


# ── 入口 ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="校园宽带自动认证")
    parser.add_argument("--watch", action="store_true", help="断线自动重连模式")
    parser.add_argument("--reset", action="store_true", help="重置保存的账号密码")
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
            log("已清除保存的账号密码")
        else:
            log("没有找到已保存的账号密码")
        return

    config = load_config()
    if config:
        student_id = config["student_id"]
        password   = config["password"]
        log(f"已加载账号：{student_id}")
    else:
        student_id, password = prompt_credentials()

    if args.watch:
        watch_mode(student_id, password)
    else:
        success = auth_with_retry(student_id, password)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
