#!/bin/sh

#by default use avcodec2 (ffmpeg2):
BUILD_ARGS="--without-dec_avcodec --with-dec_avcodec2"

echo "*******************************************************************************"
echo "Deleting existing xpra modules and temporary directories"
PYTHON_PREFIX=`python-config --prefix`
PYTHON_PACKAGES=`ls -d ${PYTHON_PREFIX}/lib/python*/site-packages | sort | tail -n 1`
rm -fr "${PYTHON_PACKAGES}/xpra"
rm -fr image/* dist/*

echo
echo "*******************************************************************************"
echo "Building and installing"
pushd ../src

svn upgrade ../.. >& /dev/null
python -c "from add_build_info import record_src_info;record_src_info()"
./setup.py clean
./setup.py install ${BUILD_ARGS}
if [ "$?" != "0" ]; then
	echo "ERROR: install failed"
	exit 1
fi
popd
echo
echo "*******************************************************************************"
echo "pyapp"
./setup.py py2app
if [ "$?" != "0" ]; then
	echo "ERROR: py2app failed"
	exit 1
fi

IMAGE_DIR="./image/Xpra.app"
CONTENTS_DIR="${IMAGE_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RSCDIR="${CONTENTS_DIR}/Resources"
HELPERS_DIR="${CONTENTS_DIR}/Helpers"
LIBDIR="${RSCDIR}/lib"
UNAME_ARCH=`uname -p`
ARCH="x86"
if [ "${UNAME_ARCH}" == "powerpc" ]; then
	ARCH="ppc"
fi
export ARCH

echo
echo "*******************************************************************************"
echo "Fixing permissions on libpython dylib"
if [ ! -z "${JHBUILD_PREFIX}" ]; then
	chmod 755 "${JHBUILD_PREFIX}/lib/"libpython*.dylib
fi
#avoid error if there is no /etc/pango:
#(which seems to be the case with newer builds)
if [ ! -d "${JHBUILD_PREFIX}/etc/pango" ]; then
	mkdir "${JHBUILD_PREFIX}/etc/pango"
fi

echo
echo "*******************************************************************************"
echo "calling 'gtk-mac-bundler Xpra.bundle' in `pwd`"
gtk-mac-bundler Xpra.bundle
if [ "$?" != "0" ]; then
	echo "ERROR: gtk-mac-bundler failed"
	exit 1
fi

echo
echo "*******************************************************************************"
echo "unzip site-packages and make python softlink without version number"
pushd ${LIBDIR} || exit 1
ln -sf python* python
cd python
unzip -nq site-packages.zip
rm site-packages.zip
popd

echo
echo "*******************************************************************************"
echo "moving pixbuf loaders to a place that will *always* work"
mv ${RSCDIR}/lib/gdk-pixbuf-2.0/*/loaders/* ${RSCDIR}/lib/
echo "remove now empty loaders dir"
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0/2.10.0
rmdir ${RSCDIR}/lib/gdk-pixbuf-2.0
echo "fix gdk-pixbuf.loaders"
LOADERS="${RSCDIR}/etc/gtk-2.0/gdk-pixbuf.loaders"
sed -i -e 's+@executable_path/../Resources/lib/gdk-pixbuf-2.0/.*/loaders/++g' "${LOADERS}"

echo
echo "*******************************************************************************"
echo "Add xpra/server/python scripts"
cp ./Python "${HELPERS_DIR}/"
cp ./Xpra "${HELPERS_DIR}/"
cp ./Keyboard_Tool "${HELPERS_DIR}/"
cp ./SSH_ASKPASS "${HELPERS_DIR}/"
# copy "python" binary as another name so we can have a process that is not called "python"
# for each one of the tools we provide a script for:
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra"
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Xpra_Launcher"
cp "${RSCDIR}/bin/python" "${RSCDIR}/bin/Keyboard_Tool"
#we dont need the wrapper installed by distutils:
rm "${MACOS_DIR}/Xpra_Launcher-bin"

# launcher needs to be in main ("MacOS" dir) since it is launched from the custom Info.plist:
cp Xpra_Launcher ${MACOS_DIR}
# Add the icon:
cp ./*.icns ${RSCDIR}/

# Add Xpra share (for icons)
rsync -rplog $XDG_DATA_DIRS/xpra/* ${RSCDIR}/share/xpra/

echo
echo "*******************************************************************************"
echo "include all codecs found: "
find $PYTHON_PACKAGES/xpra/codecs/* -type d -maxdepth 0 -exec basename {} \;
rsync -rpl $PYTHON_PACKAGES/xpra/codecs/* $LIBDIR/python/xpra/codecs/

echo
echo "*******************************************************************************"
echo "Hacks"
#HACKS
#no idea why I have to do this by hand
#add gtk .so
rsync -rpl $PYTHON_PACKAGES/gtk-2.0/* $LIBDIR/
#add pygtk .py
PYGTK_LIBDIR="$LIBDIR/pygtk/2.0/"
rsync -rpl $PYTHON_PACKAGES/pygtk* $PYGTK_LIBDIR
rsync -rpl $PYTHON_PACKAGES/cairo $PYGTK_LIBDIR
#opengl: just take everything:
rsync -rpl $PYTHON_PACKAGES/OpenGL* $LIBDIR/python/

#gst bits expect to find dylibs in Frameworks!?
pushd ${CONTENTS_DIR}
ln -sf Resources/lib Frameworks
pushd Resources/lib
echo "removing extra gstreamer dylib deps:"
for x in "libgstbasevideo*" "libgstcdda*" \
    "libgstcheck*" "libgstnetbuffer*" "libgstphotography*" \
    "libgstrtp*" "libgstrtsp*" "libgstsdp*" "libgstsignalprocessor*" \
    "libgstvideo*" \
    ; do
	echo "* removing "$x
	rm $x
done
echo "removing extra gstreamer plugins:"
GST_PLUGIN_DIR=./gstreamer-0.10
KEEP=./gstreamer-0.10.keep
mkdir ${KEEP}
for x in "libgstapp.*" "libgstaudio*" "libgstcoreelements*" \
	"libgstfaac*" "libgstfaad*" \
    "libgstflac*" "libgstlame*" "libgstmad*" "libgstmpegaudioparse*" \
    "libgstpython*" \
    "libgstogg*" "libgstoss*" "libgstosxaudio*" "libgstspeex*" \
    "libgstvolume*" "libgstvorbis*" \
    "libgstwav*"; do
	echo "* keeping "$x
	mv ${GST_PLUGIN_DIR}/$x ${KEEP}/
done
rm -fr ${GST_PLUGIN_DIR}
mv ${KEEP} ${GST_PLUGIN_DIR}
popd
popd

echo
echo "*******************************************************************************"
echo "Clean unnecessary files"
pwd
ls image
#better do this last ("rsync -C" may omit some files we actually need)
find ./image -name ".svn" | xargs rm -fr
#not sure why these get bundled at all in the first place!
find ./image -name "*.la" -exec rm -f {} \;

echo
echo "*******************************************************************************"
echo "De-duplicate dylibs"
pushd $LIBDIR
for x in `ls *dylib | sed 's+[0-9\.]*\.dylib++g' | sed 's+-$++g' | sort -u`; do
	COUNT=`ls *dylib | grep $x | wc -l`
	if [ "${COUNT}" -gt "1" ]; then
		FIRST=`ls $x* | sort -n | head -n 1`
		for f in `ls $x* | grep -v $FIRST`; do
			cmp -s $f $FIRST
			if [ "$?" == "0" ]; then
				echo "(re)symlinking $f to $FIRST"
				rm $f
				ln -sf $FIRST $f
			fi
		done
	fi
done
popd


echo
echo "*******************************************************************************"
echo "copying application image to Desktop"
rsync -rplogt "${IMAGE_DIR}" ~/Desktop/
echo "Done"
echo "*******************************************************************************"
echo
