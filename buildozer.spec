[app]
title = DoNata Lanches
icon.filename = %(source.dir)s/icon.png
package.name = donata
package.domain = br.com.donata
source.dir = .
source.include_exts = py,png,ttf
version = 1.4
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.extra_manifest_application_arguments = ./extra_manifest_application_arguments.xml
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
