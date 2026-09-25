#!/bin/sh

export NIXPKGS_ALLOW_UNFREE=1

exec nix-shell
