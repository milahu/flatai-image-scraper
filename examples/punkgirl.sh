#!/usr/bin/env bash

prompt=""
prompt+="nude punk girl"
# "Southern Europe" as in: Spain, Italy, Greece, Turkey, Persia, ...
# because "sorry" folks, i dont like people with ultra-white skin colors
# maybe also because i myself have a light-brown skin color
# also i dont like asian faces, or african faces...
# am i a "racist" now? haha. i just like people who look similar to myself
prompt+=", a person of Southern European ancestry"
prompt+=", short hair"
prompt+=", short mohawk haircut"
prompt+=", dark-red hair"
# no matter how i phrase "small tits", some models just ignore it, and always return big tits...
prompt+=", small tits"
prompt+=", petite tits"
prompt+=", tiny tits"
prompt+=", A-cup tits"
prompt+=", big ass"
prompt+=", wide hips"
prompt+=", her full body is visible"
prompt+=", clean skin"
prompt+=", sexy pose"
prompt+=", showing her front side (tits, belly, legs)"
prompt+=", vertical strip of dark pubic hair"
prompt+=", serious look on her face"
prompt+=", looking into the camera"

echo "prompt: $prompt"

# style="Flat AI Pro"
# style="Flat AI Pro+"
style="(cycle)"

# aspect=1:1
aspect=9:16

set -x # enable xtrace

# NOTE maybe add "--headless"
exec ./src/flatai_image_scraper.py "$prompt" --aspect "$aspect" --style "$style"
