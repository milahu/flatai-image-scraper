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
import binascii
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
GENERATED_IMAGE_SELECTOR = "img.generated-image"

# TODO update to sync with the server options
ASPECT_RATIOS = ("1:1", "16:9", "4:3", "9:16", "3:4")

# value: get the current value of aspect-ratio
ASPECT_RATIO_VALUE_SELECTOR = "button.fa-format-trigger > span.fa-format-short-value"

# toggle: click this element to toggle the aspect-ratio menu
# toggle = open or close
ASPECT_RATIO_DROPDOWN_TOGGLE_SELECTOR = "div.fa-image-format > button.fa-format-trigger"

# menu: container with buttons for different values
ASPECT_RATIO_DROPDOWN_MENU_SELECTOR = "div#fa-format-options.fa-dropdown-open"

# value button: click this element to set a new value for aspect-ratio
# the format string "{value}" will be replaced with an aspect ratio like "1:1" or "16:9"
ASPECT_RATIO_DROPDOWN_VALUE_BUTTON_SELECTOR = "div#fa-format-options > button[data-value='{value}']"

# all buttons of the aspect-ratio menu
# available values are stored in the "data-value" attribute of each button
ASPECT_RATIO_DROPDOWN_ALL_BUTTONS_SELECTOR = "div#fa-format-options > button"



# value: get the current value of style
# the current style name is stored in the "title" attribute
# document.querySelector("div.style-model-item.active").getAttribute("title")
STYLE_GET_VALUE_SELECTOR = "div.style-models-grid > div.style-model-item.active"

# click this element to set the style value
# document.querySelector("div.style-models-grid > div.style-model-item[role='button'][title='Flat AI Ultra']").click()
# document.querySelector("div.style-models-grid > div.style-model-item[role='button'][title='Anatomix']").click()
STYLE_SET_VALUE_SELECTOR = "div.style-models-grid > div.style-model-item[role='button'][title='{style}']"

# all values: get the values of all available styles
# each style name is stored in the "title" attribute of the div.style-model-item element
STYLE_GET_ALL_VALUES_SELECTOR = "div.style-models-grid > div.style-model-item"

# not used
# for now we can get and set the style without setting the correct style category
r'''
# the style category is stored in the "data-category" attribute
# category="general" # main styles
# category="artistic" # experimental styles
# document.querySelector("button.style-tab.active").getAttribute("data-category")
STYLE_GET_CATEGORY_SELECTOR = "button.style-tab.active"

# click this element to activate the style menu for category=value
# document.querySelector("button.style-tab[type='button'][data-category='general']").click()
# document.querySelector("button.style-tab[type='button'][data-category='artistic']").click()
STYLE_SET_CATEGORY_SELECTOR = "button.style-tab[type='button'][data-category='{value}']"
'''



# TODO update to sync with the server options
DEFAULT_STYLE = "Flat AI Ultra"
CYCLE_STYLE = "(cycle)"
RANDOM_STYLE = "(random)"
MAGIC_STYLES = (
    CYCLE_STYLE,
    RANDOM_STYLE,
)
STYLES = (
    "Flat AI Ultra",
    "Flat AI Pro+",
    "Flat AI Pro",
    "Standard",
    "Quality+",
    "Realistic",
    "Nightmare",
    "Surreal",
    "Sci-Fi",
    "80s Sci-Fi",
    "Brutalpunk",
    "Dystopia",
    "Brutalist",
    "Dieselpunk Poster",
    "50s Noir",
    "Flat Toon",
    "Blocky World",
    "Dark Fantasy",
    "Things",
    "Illustration",
    "Beauty Engine",
    "Film Noir",
    "Retro Anime",
    "CGI Illustrations",
    "Social Feed",
    "Cyber Rooms",
    "Cinematic",
    "Real Skin",
    "Mythic Fantasy",
    "Daily life",
    "Pixel Art",
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
    style_choices = list(STYLES) + list(MAGIC_STYLES)
    p.add_argument("--style", choices=style_choices, default=DEFAULT_STYLE,
                    help=(
                        f'Image style'
                        f' (default: "{DEFAULT_STYLE}")'
                        f' (random: "{RANDOM_STYLE}")'
                        f' (cycle: "{CYCLE_STYLE}")'
                        '.'
                    ))
    # upscaling is disabled by default because
    # 1. most generated images are trash
    # 2. upscaling takes lots of time
    # 3. good images can be upscaled later
    p.add_argument("--upscale", action="store_true",
                    help='Also request an upscaled version of all generated images.')
    # args.output_root
    p.add_argument("--output-root", default="output",
                    help="Output root directory (default: ./output).")
    p.add_argument("--timeout", type=float, default=180.0,
                    help="Generation/operation timeout in seconds (default: 180).")
    p.add_argument("--headless", action="store_true",
                    help='Run the web browser in headless mode.')
    args = p.parse_args()
    args.output_root = Path(args.output_root)
    return args


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


def make_input_parameters(args: argparse.Namespace, style: str, username: str) -> dict:
    # Credentials are input to the scraper, but the password is never persisted.
    return {
        "generator": GENERATOR_NAME,
        "generator_url": GENERATOR_URL,
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "style": style,
        # the username should have no effect on the generated images
        # "username": username,
    }


def make_output_dir(root: str, params: dict) -> Path:
    canonical = json.dumps(
        params, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    out = Path(root) / digest
    out.mkdir(parents=True, exist_ok=True)
    prompt_json_path = out / "prompt.json"
    if not prompt_json_path.exists():
        prompt_json_path.write_text(
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
    assert el, f"fill: no element"
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


async def consent_cookies(driver, timeout: float):
    r'''
    flatai.org asks for your consent to use your personal data to:

    1. Personalised advertising
    and content, advertising and content measurement,
    audience research and services development
    2. Store and/or access information on a device

    Your personal data will be processed and information from your device
    (cookies, unique identifiers, and other device data)
    may be stored by, accessed by and shared with 210 partners,
    or used specifically by this site.
    We and our partners may use precise geolocation data.

    Some vendors may process your personal data
    on the basis of legitimate interest,
    which you can object to by managing your options below.
    Look for a link at the bottom of this page or in the site menu
    to manage or withdraw consent in privacy and cookie settings.

    Consent
    '''
    # ...otherwise the website is not usable
    CONSENT_COOKIES_SELECTOR = "button.fc-cta-consent"
    # <button class="fc-button fc-cta-consent fc-primary-button" role="button" aria-label="Consent" tabindex="0">

    # Use the actual form's submit button.
    print("    Getting the 'consent cookies' button ...")
    try:
        submit = await wait_for_element(
            driver,
            [(By.CSS_SELECTOR, CONSENT_COOKIES_SELECTOR)],
            timeout,
        )
    except TimeoutError as exc:
        print("    Getting the 'consent cookies' button failed -> Giving up")
        # maybe the website is not asking to 'consent cookies'
        return
    print("    Getting the 'consent cookies' button done")

    print("    Clicking 'consent cookies' ...")
    await submit.click()
    print("    Clicking 'consent cookies' done")


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
    # get the current value
    elem = await wait_for_element(driver, [(By.CSS_SELECTOR, ASPECT_RATIO_VALUE_SELECTOR)], timeout)
    current_ratio = await elem.get_attribute("innerText")
    if ratio == current_ratio:
        print(f"set_aspect_ratio: nothing to do")
        return

    print(f"set_aspect_ratio: opening the aspect-ratio menu")
    elem = await wait_for_element(driver, [(By.CSS_SELECTOR, ASPECT_RATIO_DROPDOWN_TOGGLE_SELECTOR)], timeout)
    await elem.click()

    print(f"set_aspect_ratio: clicking the value button")
    selector = ASPECT_RATIO_DROPDOWN_VALUE_BUTTON_SELECTOR.format(value=ratio)
    elem = await wait_for_element(driver, [(By.CSS_SELECTOR, selector)], timeout)
    # TODO validate ratio. if ratio is invalid then elem is not found
    await elem.click()


async def set_style(driver, style: str, timeout: float):
    # get the current value
    elem = await wait_for_element(driver, [(By.CSS_SELECTOR, STYLE_GET_VALUE_SELECTOR)], timeout)
    current_style = await elem.get_attribute("title")
    if style == current_style:
        print(f"set_style: nothing to do")
        return

    print(f"set_style: clicking the value button")
    selector = STYLE_SET_VALUE_SELECTOR.format(style=style)
    try:
        elem = await wait_for_element(driver, [(By.CSS_SELECTOR, selector)], timeout=5)
    except TimeoutError as exc:
        raise ValueError(f"failed to set style {style!r}")
    await elem.click()
    print(f"    style: {style}")


async def get_all_styles(driver, timeout=30):
    styles = []
    elems = await wait_for_elements(driver, By.CSS_SELECTOR, STYLE_GET_ALL_VALUES_SELECTOR, timeout)
    for elem in elems:
        style = await elem.get_attribute("title")
        styles.append(style)
    return tuple(styles)


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


# import base64
# import os
# import tempfile
# from pathlib import Path

# from selenium import webdriver
# from selenium.webdriver.firefox.webdriver import WebDriver


# Source - https://stackoverflow.com/a/79810715
# Posted by edcsnt, modified by community. See post 'Timeline' for change history
# Retrieved 2026-10-21, License - CC BY-SA 4.0
async def fetch_blob(driver: "WebDriver", url: str) -> str | bytes:
    """Fetch binary or plain-text blob from web browser.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param url: URL of blob to fetch
    :type url: str
    :raises ValueError: A URL with an invalid scheme was passed
    :return: Binary or plain-text blob as bytes or string, respectively
    """
    script = """
        const url = arguments[0];
        const callback = arguments[arguments.length - 1];

        fetch(url).then(res => { return res.bytes(); }).then(
          B => { return B.toBase64(); },
        ).then(callback);
    """
    text_chars = bytes(
        {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}
    )

    if not url.startswith('blob:https:'):
        m = "URL must start with 'blob:https:'"
        raise ValueError(m)

    e = await driver.execute_async_script(script, url)

    f = base64.b64decode(e)

    if f.translate(None, text_chars):
        return f

    return f.decode()


async def clear_generated_image(driver, generated_image):
    """
    clear the image source
    so the next wait_for_generated_image
    does not return the previous generated image
    """
    if 1:
        # debug
        print("clearing the generated image ...")
        await asyncio.sleep(1)
    # await generated_image.set_attribute("src", "")
    arguments = [
        GENERATED_IMAGE_SELECTOR, # arguments[0]
    ]
    script = r"""
        const GENERATED_IMAGE_SELECTOR = arguments[0];
        for (const generated_image of document.querySelectorAll(GENERATED_IMAGE_SELECTOR)) {
            generated_image.setAttribute("src", "");
        }
    """
    await driver.execute_script(script, arguments)


async def wait_for_generated_image(driver, timeout: float):
    """
    Wait until Flat AI's generated image data URL has finished loading.

    Returns the image element.
    """
    deadline = time.monotonic() + timeout

    step_idx = -1
    while time.monotonic() < deadline:
        step_idx += 1
        if 1:
            # print the elapsed time every second
            print(f"{step_idx + 1} ", end="", flush=True)
            # print a new line every 10 seconds
            if (step_idx + 1) % 10 == 0:
                print()
        if 0:
            # debug
            print(f"wait_for_generated_image: step {step_idx + 1}")
        try:
            arguments = [
                GENERATED_IMAGE_SELECTOR, # arguments[0]
            ]
            js_image_json = await driver.execute_script(
                """
                const GENERATED_IMAGE_SELECTOR = arguments[0];
                const images = document.querySelectorAll(GENERATED_IMAGE_SELECTOR);

                const results = [];
                let js_image = null;

                for (const img of images) {
                    const src = img.currentSrc || img.src || "";

                    if (!img.complete) continue;
                    if (img.naturalWidth <= 0) continue;
                    if (img.naturalHeight <= 0) continue;

                    if (src.startsWith("data:image/")) {
                        js_image = {
                            srcLength: src.length,
                            width: img.naturalWidth,
                            height: img.naturalHeight
                        };
                        break;
                    }
                    else if (src.startsWith("blob:https://flatai.org/")) {
                        // example: blob:https://flatai.org/5a7879dd-8553-4a50-998f-ebe575191233
                        js_image = {
                            src: src,
                            width: img.naturalWidth,
                            height: img.naturalHeight
                        };
                        break;
                    }
                }

                if (!js_image) return null;

                const js_image_json = JSON.stringify(js_image)
                return js_image_json;
                """,
                arguments
            )

            # print(f"js_image_json: {js_image_json}")

            if js_image_json:
                js_image = json.loads(js_image_json)

                print(f"js_image: {js_image}")

                py_images = await driver.find_elements(
                    By.CSS_SELECTOR,
                    # "img",
                    GENERATED_IMAGE_SELECTOR,
                )
                # print(f"py_images: {py_images}")

                result_images = []

                if "srcLength" in js_image:
                    print(
                        "      generated image ready: "
                        f"{js_image['width']}x{js_image['height']}, "
                        f"data URL length={js_image['srcLength']}"
                    )
                elif "src" in js_image:
                    print(
                        "      generated image ready: "
                        f"{js_image['width']}x{js_image['height']}, "
                        f"blob URL={js_image['src']}"
                    )

                # Find and return the actual element.
                for img_idx, py_image in enumerate(py_images):
                    try:
                        src = await py_image.get_attribute("src")
                        if not src: continue

                        print(f"py_image[{img_idx}] = {py_image}")
                        print(f"py_image[{img_idx}].src = {src[:1000]}")

                        if (
                            "srcLength" in js_image
                            and src.startswith("data:image/")
                            and len(src) == js_image["srcLength"]
                        ):
                            return py_image
                        elif (
                            "src" in js_image
                            # and src.startswith("blob:https://flatai.org/")
                            and src == js_image["src"]
                        ):
                            return py_image

                    except Exception:
                        pass

        except Exception as exc:
            raise # debug
            pass

        # await asyncio.sleep(0.25)
        # each image takes about 60 seconds to generate
        # so we can wait a bit longer here
        await asyncio.sleep(1)

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
    image_src = await image.get_attribute("src")

    if not image_src:
        raise RuntimeError("Generated image has no src")

    if image_src.startswith("data:image/"):
        try:
            header, encoded = image_src.split(",", 1)
        except ValueError as exc:
            raise RuntimeError("Malformed image data URL") from exc

        try:
            data = base64.b64decode(encoded)
        except binascii.Error:
            # save_data_url_image: failed to decode encoded: %3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='640'%20height='360'%20viewBox='0%200%20640%20360'%3E%3C/svg%3E
            print(f"save_data_url_image: failed to decode encoded: {encoded}")
            await asyncio.sleep(999)
            raise
    elif image_src.startswith("blob:https://flatai.org/"):
        # https://stackoverflow.com/questions/47424245/how-to-download-an-image-with-python-3-selenium-if-the-url-begins-with-blob
        data = await fetch_blob(driver, image_src)

    else:
        raise RuntimeError(
            f"Expected data:image URL or blob:https URL, got {image_src[:100]!r}"
        )

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
        style,
        output_dir: Path,
        params: dict,
        upscale: bool,
        download_dir: Path,
        iteration: int,
    ):
    print(f"\n=== Generation {iteration} ===")

    # 5. Prompt
    prompt_box_selector = [
        # (By.CSS_SELECTOR, "textarea"),
        # (By.XPATH, '//textarea[contains(@placeholder,"Your prompt")]'),
        # (By.XPATH, '//textarea[contains(@aria-label,"Your prompt")]'),
        (By.CSS_SELECTOR, "textarea#prompt"),
    ]
    prompt_box = await wait_for_element(
        driver,
        prompt_box_selector,
        args.timeout,
    )
    await fill(prompt_box, args.prompt)

    if 0:
        # debug
        print(f"prompt_box: {prompt_box}")
        # assert prompt_box, f"not found prompt_box. prompt_box={prompt_box!r}"
        print("done fill prompt_box")
        await asyncio.sleep(999)

    # 6–7. Ratio and style.
    print(f"set_aspect_ratio {args.aspect_ratio!r}")
    await set_aspect_ratio(driver, args.aspect_ratio, args.timeout)
    print(f"set_style {style!r}")
    await set_style(driver, style, args.timeout)

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
    await clear_generated_image(driver, generated_image)

    # TODO? get seed from non_upscaled filename
    seed = await get_image_seed(driver)
    print(f"    seed: {seed}")

    params["seed"] = seed

    add_exif(non_upscaled, params)
    print("    EXIF metadata written")

    if upscale:
        # 13–18. Upscale is a separate Flat AI job.
        before_upscale_download = download_snapshot(download_dir)
        await upscale_current_image(driver, args.timeout)

        print("[15] Waiting for upscale generation...")
        generated_image = await wait_for_generated_image(driver, args.timeout)
        print("[16] upscaled image is ready")

        upscaled = (output_dir / seed).with_suffix(".upscaled" + IMAGE_SUFFIX)
        upscaled = await save_data_url_image(driver, generated_image, upscaled)
        print(f"[17] Saved {upscaled}")
        await clear_generated_image(driver, generated_image)

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

    # get write access
    global STYLES

    args = parse_args()
    username, password = load_credentials(args)

    upscale = args.upscale
    style = args.style
    style_idx = -1
    style_idx_max = len(STYLES) - 1

    # params = make_input_parameters(args, style, username)
    # output_dir = make_output_dir(args.output_root, params)
    #
    # # A private download directory prevents unrelated Chrome downloads from
    # # being mistaken for generated images.
    # download_dir = output_dir / ".downloads"
    # download_dir.mkdir(parents=True, exist_ok=True)

    # output_dir can change for each request
    # so we use the same download_dir for all requests
    download_dir = args.output_root

    # print(f"Output directory: {output_dir}")
    # print(f"prompt.json:      {output_dir / 'prompt.json'}")
    print(f"Download directory: {download_dir}")
    print(f"Aspect ratio:     {args.aspect_ratio}")
    print(f"Style:            {args.style}")

    options = webdriver.ChromeOptions()

    options.add_argument("--start-maximized")
    if args.headless:
        options.add_argument("--headless")
    options.update_pref("download.prompt_for_download", False)
    options.update_pref("download.directory_upgrade", True)
    options.update_pref("download.default_directory", str(download_dir.resolve()))
    options.update_pref("safebrowsing.enabled", True)

    # Allow repeated automatic downloads.
    options.update_pref("profile.default_content_setting_values.automatic_downloads", 1)

    print("Starting visible Chromium...")
    async with webdriver.Chrome(options=options) as driver:
        await login(driver, username, password, args.timeout)

        await consent_cookies(driver, args.timeout)

        print("[4] Open Image Studio")
        await driver.get(GENERATOR_URL, wait_load=True, timeout=args.timeout)

        # Let the SPA finish rendering.
        await asyncio.sleep(2)

        # get the actual available list of styles
        all_styles = await get_all_styles(driver)
        if STYLES != all_styles:
            STYLES = all_styles
            print(f"TODO update the STYLES list in {__file__}:")
            print("STYLES = (")
            for style in STYLES:
                print(f'    "{style}",')
            print(")")

        if args.style not in MAGIC_STYLES:
            # validate args.style
            if args.style not in STYLES:
                raise ValueError(f"invalid style. args.style={args.style!r} is not in STYLES={STYLES}")

        timeout_iterations = []

        iteration = 1
        while True:

            if args.style == RANDOM_STYLE:
                style = random.choice(STYLES)
                print(f"Style: {args.style!r} -> {style!r}")
            elif args.style == CYCLE_STYLE:
                style_idx += 1
                if style_idx > style_idx_max:
                    style_idx = 0
                style = STYLES[style_idx]
                print(f"Style: {args.style!r} -> {style!r}")

            params = make_input_parameters(args, style, username)
            output_dir = make_output_dir(args.output_root, params)

            print(f"Output directory: {output_dir}")
            print(f"prompt.json:      {output_dir / 'prompt.json'}")

            try:
                await one_generation(
                    driver,
                    args,
                    style,
                    output_dir,
                    params,
                    upscale,
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

            except TimeoutError as exc:
                print(f"    Timeout waiting for generated image {iteration} -> Generating next image")
                timeout_iterations.append(iteration)
                print(f"    Timeout iterations: {timeout_iterations}")
                iteration += 1

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
