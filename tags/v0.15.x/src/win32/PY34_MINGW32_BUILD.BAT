set PYTHON=C:\Python34
set PATH=%PATH%;C:\MinGW\bin
set PKG_CONFIG_PATH=C:\MinGW\lib\pkgconfig;C:\MinGW\msys\1.0\local\lib\pkgconfig;C:\MinGW\msys\1.0\lib\pkgconfig
set COMPILER_ARGS=--compiler=mingw32
set BUILD_TYPE=-MinGW
win32\MAKE-INSTALLER.BAT /silent
