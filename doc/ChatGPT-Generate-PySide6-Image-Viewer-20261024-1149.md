# Generate PySide6 Image Viewer

**User:** Anonymous  
**Created:** 2026/10/24 9:08:08  
**Updated:** 2026/10/24 9:36:46  
**Exported:** 2026/10/24 11:49:40  
**Link:** [<https://chatgpt.com/c/6adc5957-8618-83eb-82ac-6f9e1ac28883>](https://chatgpt.com/c/6adc5957-8618-83eb-82ac-6f9e1ac28883)

## Prompt:

10/24/2026, 9:12:43 AM

generate an image viewer in python, based on the pyside6 qt bindings

i need this image viewer for my image scraper ([<https://github.com/milahu/flatai-image-scraper>](https://github.com/milahu/flatai-image-scraper)) where i generate hundreds or thousands of images, and then i have to select the good images "by hand" (actually "by human eye")

so i need some keyboard control to rate images as "good" or "bad". i guess the most intuitive solution is: "arrow key up" = "good" = "thumbs up", arrow key down = "bad" = "thumbs down". and as an alias for my left hand: "E key" = "good" = "up", "D key" = "bad" = "down"

one question is: how should i store my ratings? one possible solution: use the filesystem. all the input images are stored in the directory "flatai-image-scraper/output", so all the good images could be moved to "flatai-image-scraper/good" and all the bad images could be moved to "flatai-image-scraper/bad", preserving the full original filepath like "flatai-image-scraper/output/subdir1/subdir2/name.jpg" -\> "flatai-image-scraper/good/subdir1/subdir2/name.jpg"

the image viewer app should accept an optional positional CLI parameter input_directory, which by default is "output" (the "output" from the image scraper...). also the app should have CLI parameters for the good_output_directory (by default "good") and for the bad_output_directory (by default "bad")

by default, the image viewer should present the images in random order.

the image viewer should have a CLI flag "--group-by-style". if that flag is enabled, then it first should present all images with style 1 (in random order), then all images with style 2 (in random order), and so on. each image's style is stored in the json file "prompt.json" in the directory of the image file. so for example, the image file "flatai-image-scraper/output/subdir1/subdir2/name.jpg" has its prompt-metadata stored in "flatai-image-scraper/output/subdir1/subdir2/prompt.json" (because all images in subdir2 have been generated with the same prompt, just with a different seed number, and the seed number is stored in the filename like `3751840952.jpg`).

the image viewer should have a CLI option "--style STYLE", where the user can set the style of the images he is interested in, for example, style can be a string like "Flat AI Ultra" or "Dark Fantasy". the app should not have a hardcoded list of styles, because the list of styles keeps changing over time

ok, i am out of ideas for now. generate!

## Response:

10/24/2026, 9:12:47 AM

> **Searched 6 websites**
>
> Worked for 4s

I’d build this as a **keyboard-first image reviewer** using PySide6, with filesystem-based ratings and no hardcoded list of styles.

The main design decision is to move rated images into `good/` or `bad/`, preserving their paths relative to the input directory. That makes your selections easy to use in later training, filtering, or dataset-processing scripts.

## Keyboard controls

| Key | Action |
|----|----|
| `↑` or `E` | <text color="success" weight="medium">Good</text> - move image to `good/` |
| `↓` or `D` | <text color="danger" weight="medium">Bad</text> - move image to `bad/` |
| `→` or `Space` | Skip to next image |
| `←` | Go back to the previous image |
| `U` | Undo the last rating |
| `Esc` or `Q` | Quit |

Images are scaled to fit the window, and the application displays the current filename, style, and progress.

## Get the Python application

<box border radius="xl" padding={4} gap={3}>
  <row align="center" gap={3}>
    <box background="surface-secondary" radius="lg" size="52px" align="center" justify="center">
      <icon name="file-code" size="2xl"/>
    </box>
    <box flex="1" gap={1}>
      **image_viewer.py**
      <text color="secondary" size="sm">Python · PySide6 · Single-file application</text>
      <text color="success" size="sm">Syntax checked successfully</text>
    </box>
  </row>
  [Download image_viewer.py](sandbox:/mnt/data/image_viewer.py)
</box>

## Installation and usage

Install PySide6:

Save `image_viewer.py` in your `flatai-image-scraper` repository root. Your directory layout would look like this:

Run it with the default directories:

Or specify the directories explicitly:

### Filter and organize by style

Review only one style:

Review all styles, grouped alphabetically, with images randomized within each style:

Combine both options:

For reproducible random ordering, specify a seed:

## How ratings are stored

Suppose you rate this image as good:

The app moves it to:

A bad rating moves it to the corresponding location under `bad/`. Existing files at the destination are never overwritten. The original `prompt.json` stays in `output/`, so metadata is not moved along with individual images.

**One implementation detail to verify:** I made the style reader search recursively for string-valued JSON keys named `style`, since I couldn't confirm the precise `prompt.json` schema from the repository page. If your metadata uses a different key or structure, the style filter may need a small adjustment.

The script is syntax-checked, but I haven't run the GUI against your actual scraper output. One useful next improvement would be a **thumbnail contact sheet mode** so you can review many images at once instead of loading each image individually.

## Prompt:

10/24/2026, 9:34:00 AM

nice! : )

> `U` = Undo the last rating

that is too "non-obvious". instead, the "arrow key left" (or "key S" for my left hand) should "Undo the last rating"

> → or Space Skip to next image

yes, i like that. also "key F" should "Skip to next image" (because "key F" is my left hand's "arrow key right")

also it should have a fullscreen mode, toggled with F11. by default, it should start in fullscreen mode

the image scaling is somewhat broken, as in, the images are too small. for example, if the main app window has 1200x878px, and the image canvas has 1188x733px, then an image with an original size of 1152x2048px is visible with a size of only 270x480px (in the center of the image canvas). expected: in this case, the visible image size should equal the height of the image canvas (because the image aspect ratio 1152/2048 is smaller than the image canvas aspect ratio 1188/733). and in fullscreen mode, in this case, the visible image height should equal the screen height (because the image aspect ratio 1152/2048 is smaller than the screen aspect ratio 1920/1080)

## Response:

10/24/2026, 9:34:05 AM

Nice, these changes make the controls much more intuitive! 😊

One limitation: Python's data analysis capability is temporarily unavailable, so I couldn't apply the changes to `image_viewer.py` or produce a verified updated download. The earlier version is still available here: [Download image_viewer.py](sandbox:/mnt/data/image_viewer.py).

Here is the revised control scheme I recommend:

| Key                 | Action                                       |
|---------------------|----------------------------------------------|
| `↑` / `E`           | Rate good                                    |
| `↓` / `D`           | Rate bad                                     |
| `←` / `S`           | Undo last rating                             |
| `→` / `Space` / `F` | Skip to next image                           |
| `F11`               | Toggle fullscreen                            |
| `Esc` / `Q`         | Exit fullscreen, or quit if already windowed |

The app should start in fullscreen mode.

For the scaling bug, the important changes are to give the image label an expanding size policy and scale the original pixmap to the label's actual available content area, preserving the aspect ratio:

And replace the startup call to `window.show()` with:

These are the intended fixes, not a verified update to the downloadable file. The data analysis capability is expected to become available again in about 24 hours, though that estimate isn't guaranteed.

------------------------------------------------------------------------

Powered by [ChatGPT Exporter](https://www.chatgptexporter.com)
