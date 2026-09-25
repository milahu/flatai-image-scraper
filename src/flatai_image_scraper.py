#!/usr/bin/env python3

# FIXME handle errors from the image generator
# error messages like "sorry, something went wrong, please try again"

"""
Flat AI infinite image generator/downloader.

Install:
    pip install selenium-driverless pillow piexif

Requires a Chromium/Google Chrome installation.

Default credentials:
    ./config.json
    {
      "username": "you@example.com",
      "password": "..."
    }

CLI credentials override config.json. The password is deliberately not written
to prompt.json or EXIF metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
import base64
from pathlib import Path

import piexif
from PIL import Image

from selenium_driverless import webdriver
from selenium_driverless.types.by import By


debug_generated_image_dom_change = False


GENERATOR_NAME = "Flat AI"
GENERATOR_URL = "https://flatai.org/ai-image-generator-free-no-signup/"
LOGIN_URL = "https://flatai.org/login/"
DEFAULT_CONFIG = "config.json"
IMAGE_SUFFIX = ".jpg"

ASPECT_RATIOS = ("1:1", "16:9", "4:3", "9:16", "3:4")

STYLES = (
    "Flat AI Ultra",
    "Flat AI Pro+",
    "Flat AI Pro",
    "Flat AI Base",
    "Standard",
    "Quality+",
    "Realistic",
    "Dark Fantasy",
    "Things",
    "Illustration",
    "Beauty Engine",
    "Film Noir",
    "Robot & Cyborg",
    "Retro Anime",
    "CGI Illustrations",
    "Instagramers",
    "Cyber Rooms",
    "Cinematic",
    "Flat Anime",
    "Real Skin",
    "Sci-fi Enviroments",
    "Mythic Fantasy",
    "Fantasy Armor",
    "Princess",
    "Daily life",
    "ColorART",
    "Mystical Realms",
    "Architectural",
    "1930s",
    "Hand-Painted Anime",
    "Diesel Punk",
    "Pixel Art",
    "God Eater",
    "Classic Oil Paint",
    "Anatomix",
    "Fitness",
    "Dominion",
    "Amateur",
    "Standard 2",
    "Anime Extended",
    "Studio Realistic",
)


def parse_args() -> argparse.Namespace:
    styles_help = "\n".join(f"  {s}" for s in STYLES)
    p = argparse.ArgumentParser(
        description="Continuously generate Flat AI images in visible Chromium.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"Available Flat AI styles:\n{styles_help}",
    )
    p.add_argument("prompt", help="Prompt string for the image generator.")
    p.add_argument("--username", help="Login username/email; overrides config.json.")
    p.add_argument("--password", help="Login password; overrides config.json.")
    p.add_argument("--config", default=DEFAULT_CONFIG,
                    help=f"Credentials JSON file (default: {DEFAULT_CONFIG}).")
    p.add_argument("--aspect-ratio", choices=ASPECT_RATIOS, default="1:1",
                    help="Image aspect ratio (default: 1:1).")
    p.add_argument("--style", choices=STYLES, default="Flat AI Ultra",
                    help='Image style (default: "Flat AI Ultra").')
    p.add_argument("--output-root", default="output",
                    help="Output root directory (default: ./output).")
    p.add_argument("--timeout", type=float, default=180.0,
                    help="Generation/operation timeout in seconds (default: 180).")
    return p.parse_args()


def load_credentials(args: argparse.Namespace) -> tuple[str, str]:
    username, password = args.username, args.password
    if username is None or password is None:
        path = Path(args.config)
        if not path.exists():
            missing = []
            if username is None:
                missing.append("--username")
            if password is None:
                missing.append("--password")
            raise SystemExit(
                f"Missing {', '.join(missing)} and {path} does not exist."
            )
        cfg = json.loads(path.read_text(encoding="utf-8"))
        username = username if username is not None else cfg.get("username")
        password = password if password is not None else cfg.get("password")
    if not username or not password:
        raise SystemExit("Both username and password are required.")
    return username, password


def make_input_parameters(args: argparse.Namespace, username: str) -> dict:
    # Credentials are input to the scraper, but the password is never persisted.
    return {
        "generator": GENERATOR_NAME,
        "generator_url": GENERATOR_URL,
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "style": args.style,
        "username": username,
    }


def make_output_dir(root: str, params: dict) -> Path:
    canonical = json.dumps(
        params, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    out = Path(root) / digest
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


async def wait_for_element(driver, selectors, timeout: float):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        for by, value in selectors:
            try:
                return await driver.find_element(by, value, timeout=1)
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Element not found: {selectors!r}") from last_error


async def wait_for_elements(driver, by, value, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            elems = await driver.find_elements(by, value)
            if elems:
                return elems
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Elements not found: {by}={value}")


async def click_text(driver, text: str, timeout: float, exact: bool = True):
    # XPath literal helper (handles apostrophes in labels).
    def lit(s):
        if "'" not in s:
            return f"'{s}'"
        if '"' not in s:
            return f'"{s}"'
        parts = s.split("'")
        return "concat(" + ", \"'\", ".join(f"'{x}'" for x in parts) + ")"

    t = lit(text)
    if exact:
        xpath = (
            f"//*[normalize-space(text())={t} or @aria-label={t} or @title={t}]"
        )
    else:
        xpath = (
            f"//*[contains(normalize-space(.),{t}) or "
            f"contains(@aria-label,{t}) or contains(@title,{t})]"
        )
    el = await wait_for_element(driver, [(By.XPATH, xpath)], timeout)
    # await el.click(move_to=True)
    await js_click(el)
    return el


async def js_click(el):
    await el.execute_script(
        """
        const el = arguments[0];

        el.scrollIntoView({
            block: "center",
            inline: "center"
        });

        el.click();
        """,
        el,
    )


async def fill(el, value: str):
    await el.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];

        el.focus();

        const proto = el instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;

        const setter = Object.getOwnPropertyDescriptor(
            proto,
            "value"
        ).set;

        setter.call(el, value);

        el.dispatchEvent(new Event("input", {
            bubbles: true,
            composed: true
        }));

        el.dispatchEvent(new Event("change", {
            bubbles: true,
            composed: true
        }));

        el.blur();
        """,
        el,
        value,
    )

    # Optional but useful: verify the browser accepted it.
    actual = await el.get_attribute("value")
    if actual != value:
        raise RuntimeError(
            f"Failed to fill element: expected {value!r}, got {actual!r}"
        )


async def login(driver, username: str, password_value: str, timeout: float):
    print("[1] Opening login URL")
    await driver.get(LOGIN_URL, wait_load=True, timeout=timeout)

    email = await wait_for_element(
        driver,
        [
            (By.ID, "fa-auth-email"),
            (By.CSS_SELECTOR, 'input[type="email"]'),
            (By.CSS_SELECTOR, 'input[name="email"]'),
        ],
        timeout,
    )

    pw = await wait_for_element(
        driver,
        [
            (By.ID, "fa-auth-password"),
            (By.CSS_SELECTOR, 'input[type="password"]'),
            (By.CSS_SELECTOR, 'input[name="password"]'),
        ],
        timeout,
    )

    print("[2] Entering login data")

    await fill(email, username)
    await asyncio.sleep(0.5)

    await fill(pw, password_value)
    await asyncio.sleep(1.0)

    # Verify the fields really contain what we expect.
    actual_email = await email.get_attribute("value")
    actual_password = await pw.get_attribute("value")

    print(f"    email: {actual_email!r}")
    print(f"    password length: {len(actual_password or '')}")

    if actual_email != username:
        raise RuntimeError("Email field contains unexpected value")

    if actual_password != password_value:
        raise RuntimeError("Password field contains unexpected value")

    r'''
    # Enable network logging.
    await driver.execute_cdp_cmd("Network.enable", {})

    async def on_response(event):
        response = event.get("response", {})
        url = response.get("url", "")
        status = response.get("status")

        if any(
            word in url.lower()
            for word in ("login", "auth", "session", "token")
        ):
            print(f"[AUTH] HTTP {status} {url}")

    await driver.add_cdp_listener(
        "Network.responseReceived",
        on_response,
    )
    '''

    # Use the actual form's submit button.
    submit = await wait_for_element(
        driver,
        [
            (By.CSS_SELECTOR,
             'form[data-auth-form="login"] button[type="submit"]'),
            (By.CSS_SELECTOR,
             '#fa-auth button[type="submit"]'),
        ],
        timeout,
    )

    print("[2] Clicking Sign in")
    await submit.click()
    print("[2] Sign in clicked")

    print("[3] Waiting for login result")

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            url = await driver.current_url

            print(f"    URL: {url}")

            if "/login" not in url.lower():
                print("[3] Login completed")
                return

            # Check whether the login form still exists.
            forms = await driver.find_elements(
                By.CSS_SELECTOR,
                'form[data-auth-form="login"]',
            )

            if not forms:
                print("    login form disappeared")

        except Exception as exc:
            print(f"    login status check: {exc!r}")

        await asyncio.sleep(1)

    raise TimeoutError(
        "Login did not complete before timeout."
    )


async def select_dropdown_text(driver, label: str, value: str, timeout: float):
    """
    Click a control whose nearby text/aria-label/title identifies it, then
    click the requested option. The generic fallback is useful if the frontend
    changes from <select> to a custom dropdown.
    """
    # Native select first.
    selects = await driver.find_elements(By.CSS_SELECTOR, "select")
    for s in selects:
        try:
            txt = (await s.get_attribute("aria-label")) or ""
            name = (await s.get_attribute("name")) or ""
            if label.lower() in f"{txt} {name}".lower():
                await s.execute_script(
                    "const s=arguments[0],v=arguments[1];"
                    "s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));",
                    s, value,
                )
                return
        except Exception:
            pass

    # Custom dropdown: locate text/aria-label first.
    candidates = [
        (By.XPATH, f'//*[@aria-label="{label}"]'),
        (By.XPATH, f'//*[@title="{label}"]'),
        (By.XPATH, f'//*[normalize-space(text())="{label}"]'),
        (By.XPATH, f'//*[contains(normalize-space(.),"{label}")]'),
    ]
    control = await wait_for_element(driver, candidates, timeout)
    # await control.click(move_to=True)
    await js_click(control)
    await click_text(driver, value, timeout, exact=True)


async def set_aspect_ratio(driver, ratio: str, timeout: float):
    # The Flat AI UI may expose ratio buttons directly.
    try:
        await click_text(driver, ratio, timeout, exact=True)
        print(f"    aspect ratio: {ratio}")
        return
    except TimeoutError:
        pass

    # Try common custom-select containers.
    await select_dropdown_text(driver, "Aspect Ratio", ratio, timeout)
    print(f"    aspect ratio: {ratio}")


async def set_style(driver, style: str, timeout: float):
    # The style gallery is normally directly clickable.
    try:
        await click_text(driver, style, timeout, exact=True)
        print(f"    style: {style}")
        return
    except TimeoutError:
        pass

    await select_dropdown_text(driver, "Style", style, timeout)
    print(f"    style: {style}")


def download_snapshot(download_dir: Path) -> dict[str, float]:
    result = {}
    for p in download_dir.iterdir():
        if p.is_file():
            try:
                result[p.name] = p.stat().st_mtime_ns
            except OSError:
                pass
    return result


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem}.{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def add_exif(path: Path, params: dict):
    """
    EXIF has no universally-defined fields for every application-specific
    input. We therefore store the complete JSON in EXIF UserComment and also
    expose the prompt/generator in standard EXIF fields where possible.
    """
    params_json = json.dumps(params, ensure_ascii=False, sort_keys=True)

    try:
        exif = piexif.load(str(path))
    except Exception:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    zeroth = exif.setdefault("0th", {})
    exif_ifd = exif.setdefault("Exif", {})

    zeroth[piexif.ImageIFD.ImageDescription] = params["prompt"].encode("utf-8")
    zeroth[piexif.ImageIFD.Software] = GENERATOR_NAME.encode("utf-8")
    # EXIF UserComment: ASCII prefix followed by UTF-8 JSON.
    exif_ifd[piexif.ExifIFD.UserComment] = b"UNICODE\0" + params_json.encode("utf-8")

    # Also preserve a compact JSON copy in XPComment when supported by viewers.
    try:
        zeroth[piexif.ImageIFD.XPComment] = params_json.encode("utf-16le") + b"\x00\x00"
    except Exception:
        pass

    exif_bytes = piexif.dump(exif)

    # Preserve image data/format while replacing EXIF.
    with Image.open(path) as im:
        if "exif" in im.info:
            im.save(path, exif=exif_bytes)
        else:
            im.save(path, exif=exif_bytes)


async def wait_for_generated_image(driver, timeout: float):
    """
    Wait until Flat AI's generated image data URL has finished loading.

    Returns the image element.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            raw = await driver.execute_script(
                """
                const images = [...document.images];

                for (const img of images) {
                    const src = img.currentSrc || img.src || "";

                    if (
                        src.startsWith("data:image/") &&
                        img.complete &&
                        img.naturalWidth > 0 &&
                        img.naturalHeight > 0
                    ) {
                        return JSON.stringify({
                            srcLength: src.length,
                            width: img.naturalWidth,
                            height: img.naturalHeight
                        });
                    }
                }

                return null;
                """
            )

            if raw:
                result = json.loads(raw)

                print(
                    "    generated image ready: "
                    f"{result['width']}x{result['height']}, "
                    f"data URL length={result['srcLength']}"
                )

                # Find and return the actual element.
                images = await driver.find_elements(
                    By.CSS_SELECTOR,
                    "img",
                )

                for img in images:
                    try:
                        src = await img.get_attribute("src")

                        if (
                            src
                            and src.startswith("data:image/")
                            and len(src) == result["srcLength"]
                        ):
                            return img

                    except Exception:
                        pass

        except Exception:
            pass

        await asyncio.sleep(0.25)

    raise TimeoutError(
        "Generated image did not become available before timeout."
    )


async def wait_for_generate_button(driver, timeout: float):
    return await wait_for_element(
        driver,
        [
            (By.ID, "generateButton"),
            (By.CSS_SELECTOR, "#generateButton"),
        ],
        timeout,
    )


async def save_data_url_image(
        driver,
        image,
        target: Path,
    ) -> Path:
    data_url = await image.get_attribute("src")

    if not data_url:
        raise RuntimeError("Generated image has no src")

    if not data_url.startswith("data:image/"):
        raise RuntimeError(
            f"Expected data:image URL, got {data_url[:100]!r}"
        )

    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise RuntimeError("Malformed image data URL") from exc

    data = base64.b64decode(encoded)

    target = unique_target(target)
    target.write_bytes(data)

    print(
        f"    saved {target} "
        f"({len(data):,} bytes)"
    )

    return target


async def get_image_seed(driver, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            raw = await driver.execute_script(
                """
                const el = document.querySelector(
                    ".image-toolbar .seed-value"
                );

                if (!el) {
                    return null;
                }

                const seed = el.textContent.trim();

                return seed || null;
                """
            )

            if raw:
                seed = str(raw).strip()

                if seed.isdigit():
                    return seed

        except Exception:
            pass

        await asyncio.sleep(0.1)

    raise TimeoutError(
        "Image seed did not become available before timeout."
    )


async def upscale_current_image(driver, timeout: float):
    print("[13] Open Tools menu")
    try:
        await click_text(driver, "Tools", timeout, exact=True)
    except TimeoutError:
        await click_text(driver, "Tools", timeout, exact=False)

    print("[14] Click Upscale")
    await click_text(driver, "Upscale", timeout, exact=True)


async def one_generation(
        driver,
        args,
        output_dir: Path,
        params: dict,
        download_dir: Path,
        iteration: int,
    ):
    print(f"\n=== Generation {iteration} ===")

    # 5. Prompt
    prompt_box = await wait_for_element(
        driver,
        [
            (By.CSS_SELECTOR, "textarea"),
            (By.XPATH, '//textarea[contains(@placeholder,"Your prompt")]'),
            (By.XPATH, '//textarea[contains(@aria-label,"Your prompt")]'),
        ],
        args.timeout,
    )
    await fill(prompt_box, args.prompt)

    # 6–7. Ratio and style.
    await set_aspect_ratio(driver, args.aspect_ratio, args.timeout)
    await set_style(driver, args.style, args.timeout)

    # 8. Generate.
    print("[8] Click Generate")
    if debug_generated_image_dom_change:
        await debug_generator_state(driver, "BEFORE GENERATE")
    before_download = download_snapshot(download_dir)
    generate = await wait_for_generate_button(driver, args.timeout)
    # await generate.click(move_to=True)
    await js_click(generate)

    if debug_generated_image_dom_change:
        # debug
        print("[8] Generate clicked")
        await debug_watch_generator(
            driver,
            seconds=99999999,
        )
        raise RuntimeError("Stopped after generator debugging")

    print("[9] Waiting for generated image...")
    generated_image = await wait_for_generated_image(driver, args.timeout)
    print("[10] Generated image is ready")
    seed = await get_image_seed(driver)
    print(f"    seed: {seed}")
    non_upscaled = (output_dir / seed).with_suffix(IMAGE_SUFFIX)
    non_upscaled = await save_data_url_image(driver, generated_image, non_upscaled)
    print(f"[11] Saved {non_upscaled}")

    # 13–18. Upscale is a separate Flat AI job.
    before_upscale_download = download_snapshot(download_dir)
    await upscale_current_image(driver, args.timeout)

    print("[15] Waiting for upscale generation...")
    generated_image = await wait_for_generated_image(driver, args.timeout)
    print("[16] upscaled image is ready")
    seed = await get_image_seed(driver)
    print(f"    seed: {seed}")
    upscaled = (output_dir / seed).with_suffix(".upscaled" + IMAGE_SUFFIX)
    upscaled = await save_data_url_image(driver, generated_image, upscaled)
    print(f"[17] Saved {upscaled}")

    # Add the same input metadata to both files.
    add_exif(non_upscaled, params)
    add_exif(upscaled, params)
    print("    EXIF metadata written")


async def debug_generator_state(driver, label: str):
    raw = await driver.execute_script(
        """
        const result = {
            url: location.href,
            title: document.title,
            bodyText: (document.body.innerText || "").substring(0, 3000),
            images: [],
            links: [],
            buttons: []
        };

        for (const img of document.images) {
            const src = img.currentSrc || img.src || "";

            result.images.push({
                src: src.startsWith("data:")
                    ? "data:... (" + src.length + " chars)"
                    : src.substring(0, 300),
                width: img.naturalWidth,
                height: img.naturalHeight,
                complete: img.complete,
                alt: img.alt || "",
                visible: !!(
                    img.offsetWidth ||
                    img.offsetHeight ||
                    img.getClientRects().length
                )
            });
        }

        for (const a of document.querySelectorAll("a")) {
            const href = a.href || "";

            if (
                href.includes("/ai-image/") ||
                href.includes("/image/") ||
                /\\.(jpg|jpeg|png|webp)(\\?|$)/i.test(href)
            ) {
                result.links.push({
                    href: href.substring(0, 300),
                    text: (a.innerText || "").trim().substring(0, 100)
                });
            }
        }

        for (const button of document.querySelectorAll("button")) {
            const text = (button.innerText || "").trim();

            if (
                text ||
                button.id ||
                button.getAttribute("aria-label")
            ) {
                result.buttons.push({
                    id: button.id || "",
                    text: text.substring(0, 100),
                    aria: button.getAttribute("aria-label") || "",
                    disabled: !!button.disabled
                });
            }
        }

        return JSON.stringify(result);
        """
    )

    state = json.loads(raw)

    print(f"\n--- generator state: {label} ---")
    print(f"URL: {state['url']}")
    print(f"TITLE: {state['title']}")

    print("TEXT:")
    print(state["bodyText"])

    print("IMAGES:")
    for i, img in enumerate(state["images"]):
        if img["src"].startswith("https://flatai.org/wp-content/uploads/"):
            continue
        if img["src"] == "https://flatai.org/ai-image-generator-free-no-signup/":
            continue
        if img["src"] == "":
            continue
        print(
            f"  IMG[{i}]: "
            f"{img['width']}x{img['height']} "
            f"complete={img['complete']} "
            f"visible={img['visible']} "
            f"src={img['src']!r} "
            f"alt={img['alt']!r}"
        )

    print("LINKS:")
    for i, link in enumerate(state["links"]):
        print(
            f"  LINK[{i}]: "
            f"href={link['href']!r} "
            f"text={link['text']!r}"
        )

    if 0:
        print("BUTTONS:")
        for i, button in enumerate(state["buttons"]):
            print(
                f"  BUTTON[{i}]: "
                f"id={button['id']!r} "
                f"text={button['text']!r} "
                f"aria={button['aria']!r} "
                f"disabled={button['disabled']}"
            )


async def debug_watch_generator(driver, seconds: float = 60.0):
    print(f"\nWatching generator DOM for {seconds:.0f} seconds...")

    previous = None
    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        raw = await driver.execute_script(
            """
            const result = {
                url: location.href,
                images: [],
                buttons: [],
                text: (document.body.innerText || "").substring(0, 5000)
            };

            for (const img of document.images) {
                const src = img.currentSrc || img.src || "";

                result.images.push({
                    src: src.startsWith("data:")
                        ? "data:... (" + src.length + " chars)"
                        : src.substring(0, 200),
                    width: img.naturalWidth,
                    height: img.naturalHeight,
                    complete: img.complete,
                    visible: !!(
                        img.offsetWidth ||
                        img.offsetHeight ||
                        img.getClientRects().length
                    )
                });
            }

            for (const button of document.querySelectorAll("button")) {
                result.buttons.push({
                    id: button.id || "",
                    text: (button.innerText || "").trim().substring(0, 100),
                    disabled: !!button.disabled,
                    aria: button.getAttribute("aria-label") || ""
                });
            }

            return JSON.stringify(result);
            """
        )

        state = json.loads(raw)

        current = json.dumps(
            state,
            sort_keys=True,
            ensure_ascii=False,
        )

        if current != previous:
            print("\n--- DOM CHANGE ---")
            print(f"URL: {state['url']}")

            print("IMAGES:")
            for i, img in enumerate(state["images"]):
                if img["src"].startswith("https://flatai.org/wp-content/uploads/"):
                    continue
                if img["src"] == "https://flatai.org/ai-image-generator-free-no-signup/":
                    continue
                if img["src"] == "":
                    continue
                print(
                    f"  IMG[{i}]: "
                    f"{img['width']}x{img['height']} "
                    f"complete={img['complete']} "
                    f"visible={img['visible']} "
                    f"src={img['src']!r}"
                )

            if 0:
                print("BUTTONS:")
                for i, button in enumerate(state["buttons"]):
                    print(
                        f"  BUTTON[{i}]: "
                        f"id={button['id']!r} "
                        f"text={button['text']!r} "
                        f"disabled={button['disabled']} "
                        f"aria={button['aria']!r}"
                    )

                print("PAGE TEXT:")
                print(state["text"])

            previous = current

        await asyncio.sleep(0.5)

    print("\nFinished DOM watch.")


async def main_async():
    args = parse_args()
    username, password = load_credentials(args)

    params = make_input_parameters(args, username)
    output_dir = make_output_dir(args.output_root, params)

    # A private download directory prevents unrelated Chrome downloads from
    # being mistaken for generated images.
    download_dir = output_dir / ".downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {output_dir}")
    print(f"prompt.json:      {output_dir / 'prompt.json'}")
    print(f"Aspect ratio:     {args.aspect_ratio}")
    print(f"Style:            {args.style}")

    options = webdriver.ChromeOptions()

    # Headful is the default: do NOT add --headless.
    options.add_argument("--start-maximized")
    options.update_pref("download.prompt_for_download", False)
    options.update_pref("download.directory_upgrade", True)
    options.update_pref("download.default_directory", str(download_dir.resolve()))
    options.update_pref("safebrowsing.enabled", True)

    # Allow repeated automatic downloads.
    options.update_pref("profile.default_content_setting_values.automatic_downloads", 1)

    print("Starting visible Chromium...")
    async with webdriver.Chrome(options=options) as driver:
        await login(driver, username, password, args.timeout)

        print("[4] Open Image Studio")
        await driver.get(GENERATOR_URL, wait_load=True, timeout=args.timeout)

        # Let the SPA finish rendering.
        await asyncio.sleep(2)

        iteration = 1
        while True:
            try:
                await one_generation(
                    driver,
                    args,
                    output_dir,
                    params,
                    download_dir,
                    iteration,
                )
                iteration += 1

                # Step 19: repeat from Generate. The prompt/ratio/style remain
                # selected, so the next iteration begins with Generate.
                await asyncio.sleep(0.5)

            except KeyboardInterrupt:
                print("\nStopping.")
                break
            except Exception as exc:
                print(f"\nGeneration {iteration} failed: {exc!r}", file=sys.stderr)
                # print("The browser remains open. Retrying after 5 seconds...", file=sys.stderr)
                # await asyncio.sleep(5)
                raise # debug


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
