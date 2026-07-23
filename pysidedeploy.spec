[app]
title = WhisperFlow Local
project_dir = .
input_file = app_entry.py
exec_directory = .build
project_file = 
icon = assets/icon.png

[python]
python_path = /Users/shawnvanbrunt/Developer/whisperflow-local/.venv/bin/python3
packages = Nuitka==2.7.11

[qt]
qml_files = 
excluded_qml_plugins = 
modules = Core,DBus,Gui,Widgets
plugins = accessiblebridge,egldeviceintegrations,generic,iconengines,imageformats,platforminputcontexts,platforms,platforms/darwin,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[nuitka]
macos.permissions = NSMicrophoneUsageDescription:WhisperFlow Local uses the microphone only while you dictate and processes audio locally.,NSAppleEventsUsageDescription:WhisperFlow Local uses macOS automation only for compatibility diagnostics and never sends dictated text elsewhere.
mode = standalone
extra_args = --macos-create-app-bundle --macos-app-name="WhisperFlow Local" --macos-app-mode=ui-element --macos-signed-app-name=com.shawnvanbrunt.whisperflow-local --macos-app-version=0.2.0 --macos-prohibit-multiple-instances --include-data-files=config.yaml=config.yaml --include-data-dir=assets=assets --include-data-dir=samples=samples --include-package=whisperflow_local --include-package=lightning_whisper_mlx --include-package-data=lightning_whisper_mlx --include-package=mlx --include-package-data=mlx --include-package=scipy.signal --include-module=scipy._cyutility --include-module=mlx._reprlib_fix --include-module=AppKit --include-module=Foundation --include-module=ApplicationServices --include-module=AVFoundation --nofollow-import-to=tkinter,torch,torchvision,torchaudio,tensorflow,jax,jaxlib,pytest,_pytest --module-parameter=numba-disable-jit=yes --assume-yes-for-downloads

[android]
wheel_pyside = 
wheel_shiboken = 
plugins = 

[buildozer]
mode = debug
recipe_dir = 
jars_dir = 
ndk_path = 
sdk_path = 
local_libs = 

