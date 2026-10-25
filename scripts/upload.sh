#!/usr/bin/env bash

set -e
set -u
# set -x # debug

upload_number="$1"
jpg_name="$2"

title_prefix="punk girl"

default_tags=(
  beauty
  body
  darkhair
  darkredhair
  digitalart
  frontside
  mohawk
  nude
  photography
  photorealistic
  punkgirl
  pussy
  redhair
  sexy
  shorthair
  whiteskin
  seriousface
  mohawkhaircut
  notattoos
  flatai

  # TODO choose
  shavedpussy
  hairypussy

  # TODO choose
  smalltits
  mediumtits

  # TODO choose
  longmohawk
)

jpg="$(find output* good bad -type f -name "$jpg_name")"

if ! [ -e "$jpg" ]; then
  echo "error: not found jpg with name $jpg_name"
  exit 1
fi

jpg="$(readlink -f "$jpg")"
echo "todo: upscale this jpg: $jpg"
png=${jpg%.*}.upscaled.png
png2=${jpg%.*}.upscaled.done-upload-$upload_number.png

if [ -e "$png" ]; then
  echo "using existing png $png"
else
  upscaled_download="$HOME/Downloads/flatai-generated-image-seed-N_A.jpg"
  if [ -e "$upscaled_download" ]; then
    echo "moving old upscaled_download"
    mv -v "$upscaled_download" "$upscaled_download.bak.$(date +%s)"
  fi
  echo "waiting for upscaled_download $upscaled_download"
  while true; do
    sleep 1
    if ! [ -e "$upscaled_download" ]; then continue; fi
    mv -v "$upscaled_download" $png
    break
  done
fi

prompt_hash="$(basename $(dirname "$jpg"))"
echo "prompt hash: $prompt_hash"

jpg_seed="$(basename "$jpg")"
jpg_seed=${jpg_seed%.*} # remove ".jpg" extension
echo "jpg seed: ${jpg_seed@Q}"

echo
echo "-------------------------------------------------------------"
echo
echo "todo: upload to https://www.deviantart.com/studio?new=1"
echo
echo "image path:"
echo "$png"
echo

# assumed png file path format:
# $PWD/good/$prompt_hash/$jpg_seed.upscaled.png
normalized_file_path="$(echo "$png" | sed -E "s|^.*/$prompt_hash/|flatai-image-scraper/output/$prompt_hash/|")"

prompt_json="$(find output* -path "*/$prompt_hash/prompt.json")"
if ! [ -e "$prompt_json" ]; then
  echo "error: not found prompt.json file for prompt_hash=$prompt_hash"
else
  echo "title:"
  echo "$title_prefix $upload_number"
  echo
  echo "Label options:   [x] Mature   [ ] NoAI   [x] Created using AI tools"
  echo
  echo "tags:"
  echo "${default_tags[@]}"
  echo
  echo "Display options: Original"
  echo
  echo "---------------------- description -------------------------------"
  jq -r '.prompt' <"$prompt_json"
  echo
  echo "style: $(jq -r '.style' <"$prompt_json")"
  echo
  echo "aspect ratio: $(jq -r '.aspect_ratio' <"$prompt_json")"
  echo
  echo "seed: $jpg_seed"
  echo
  echo "generator: https://flatai.org/ai-image-generator-free-no-signup/"
  echo
  echo "file path: $normalized_file_path"
  echo "-------------------------------------------------------------------"
fi

if ! [ -e "$png2" ]; then
  ln -sr $png $png2
fi

fav_jpg=fav/$(basename "$jpg")
if [ -e "$fav_jpg" ]; then
  mv -v fav/$(basename "$jpg") fav/done-upload/
fi
