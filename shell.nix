{ pkgs ? import <nixpkgs> {} }:

with pkgs;

mkShell {
  buildInputs = [
    (python3.withPackages (pp: with pp; [
      nur.repos.milahu.python3.pkgs.selenium-driverless
      nur.repos.milahu.python3.pkgs.cdp-socket
      pillow
      piexif
    ]))
  ];
}
