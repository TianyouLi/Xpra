#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from xpra.log import Logger
log = Logger("codec", "loader")

if sys.version > '3':
    unicode = str           #@ReservedAssignment

#these codecs may well not load because we
#do not require the libraries to be installed
NOWARN = ["nvenc3", "nvenc4", "nvenc5", "opencl"]

codec_errors = {}
codecs = {}
def codec_import_check(name, description, top_module, class_module, *classnames):
    log("%s:", name)
    log(" codec_import_check%s", (name, description, top_module, class_module, classnames))
    try:
        try:
            __import__(top_module, {}, {}, [])
        except ImportError as e:
            log(" cannot import %s (%s): %s", name, description, e)
            log("", exc_info=True)
            codec_errors[name] = e
            return None
    except Exception as e:
        log.warn(" cannot load %s (%s):", name, description, exc_info=True)
        codec_errors[name] = e
        return None
    try:
        #module is present
        try:
            log(" %s found, will check for %s in %s", top_module, classnames, class_module)
            for classname in classnames:
                ic =  __import__(class_module, {}, {}, classname)
                selftest = getattr(ic, "selftest", None)
                log("%s.selftest=%s", name, selftest)
                if selftest:
                    selftest()
                #log.warn("codec_import_check(%s, ..)=%s" % (name, ic))
                log(" found %s : %s", name, ic)
                codecs[name] = ic
                return ic
        except ImportError as e:
            codec_errors[name] = e
            l = log.warn
            if name in NOWARN:
                l = log.debug
            l(" cannot import %s (%s): %s", name, description, e)
            log("", exc_info=True)
    except Exception as e:
        codec_errors[name] = e
        log.warn(" cannot load %s (%s): %s missing from %s: %s", name, description, classname, class_module, e)
        log.warn("", exc_info=True)
    return None
codec_versions = {}
def add_codec_version(name, top_module, version="get_version()", alt_version="__version__"):
    try:
        fieldnames = [x for x in (version, alt_version) if x is not None]
        for fieldname in fieldnames:
            f = fieldname
            if f.endswith("()"):
                f = version[:-2]
            module = __import__(top_module, {}, {}, [f])
            if not hasattr(module, f):
                continue
            v = getattr(module, f)
            if fieldname.endswith("()") and v:
                v = v()
            global codec_versions
            codec_versions[name] = v
            #optional info:
            if hasattr(module, "get_info"):
                info = getattr(module, "get_info")
                log(" %s %s.%s=%s", name, top_module, info, info())
            return v
        if name in codecs:
            log.warn(" cannot find %s in %s", " or ".join(fieldnames), module)
        else:
            log(" no version information for missing codec %s", name)
    except ImportError as e:
        #not present
        log(" cannot import %s: %s", name, e)
        log("", exc_info=True)
    except Exception as e:
        log.warn("error during codec import: %s", e)
        log("", exc_info=True)
    return None

def PIL_logging_workaround():
    import logging
    PIL_DEBUG = os.environ.get("XPRA_PIL_DEBUG", "0")=="1"
    if PIL_DEBUG:
        from xpra.log import Logger
        log = Logger("util")
        log.info("enabling PIL.DEBUG")
        level = logging.DEBUG
    else:
        level = logging.INFO

    #newer versions use this logger,
    #we must initialize it before we load the class:
    for x in ("Image", "PngImagePlugin", "WebPImagePlugin", "JpegImagePlugin"):
        logger = logging.getLogger("PIL.%s" % x)
        logger.setLevel(level)
    import PIL
    from PIL import Image
    assert PIL and Image
    if hasattr(Image, "DEBUG"):
        #for older versions (pre 3.0), use Image.DEBUG flag:
        Image.DEBUG = int(PIL_DEBUG)

loaded = False
def load_codecs():
    global loaded
    if loaded:
        return
    loaded = True
    log("loading codecs")
    try:
        PIL_logging_workaround()
    except:
        log("error in PIL logging workaround", exc_info=True)
    codec_import_check("PIL", "Python Imaging Library", "PIL", "PIL", "Image")
    add_codec_version("PIL", "PIL.Image", "PILLOW_VERSION", "VERSION")

    codec_import_check("enc_vpx", "vpx encoder", "xpra.codecs.vpx", "xpra.codecs.vpx.encoder", "Encoder")
    codec_import_check("dec_vpx", "vpx decoder", "xpra.codecs.vpx", "xpra.codecs.vpx.decoder", "Decoder")
    add_codec_version("vpx", "xpra.codecs.vpx.encoder")

    codec_import_check("enc_x264", "x264 encoder", "xpra.codecs.enc_x264", "xpra.codecs.enc_x264.encoder", "Encoder")
    add_codec_version("x264", "xpra.codecs.enc_x264.encoder")

    codec_import_check("enc_x265", "x265 encoder", "xpra.codecs.enc_x265", "xpra.codecs.enc_x265.encoder", "Encoder")
    add_codec_version("x265", "xpra.codecs.enc_x265.encoder")

    for v in (4, 3, 5):
        codec_import_check("nvenc%s" % v, "nvenc encoder", "xpra.codecs.nvenc%s" % v, "xpra.codecs.nvenc%s.encoder" % v, "Encoder")
        add_codec_version("nvenc%s" % v, "xpra.codecs.nvenc%s.encoder" % v)

    codec_import_check("csc_swscale", "swscale colorspace conversion", "xpra.codecs.csc_swscale", "xpra.codecs.csc_swscale.colorspace_converter", "ColorspaceConverter")
    add_codec_version("swscale", "xpra.codecs.csc_swscale.colorspace_converter")

    codec_import_check("csc_cython", "cython colorspace conversion", "xpra.codecs.csc_cython", "xpra.codecs.csc_cython.colorspace_converter", "ColorspaceConverter")
    add_codec_version("cython", "xpra.codecs.csc_cython.colorspace_converter")

    codec_import_check("csc_opencl", "OpenCL colorspace conversion", "xpra.codecs.csc_opencl", "xpra.codecs.csc_opencl.colorspace_converter", "ColorspaceConverter")
    add_codec_version("opencl", "xpra.codecs.csc_opencl.colorspace_converter")

    codec_import_check("dec_avcodec2", "avcodec2 decoder", "xpra.codecs.dec_avcodec2", "xpra.codecs.dec_avcodec2.decoder", "Decoder")
    add_codec_version("avcodec2", "xpra.codecs.dec_avcodec2.decoder")

    codec_import_check("enc_webp", "webp encoder", "xpra.codecs.webp", "xpra.codecs.webp.encode", "compress")
    add_codec_version("enc_webp", "xpra.codecs.webp.encode")

    codec_import_check("dec_webp", "webp decoder", "xpra.codecs.webp", "xpra.codecs.webp.decode", "decompress")
    add_codec_version("dec_webp", "xpra.codecs.webp.decode")

    #not really a codec, but gets used by codecs:
    add_codec_version("numpy", "numpy")

    log("done loading codecs")
    log("found:")
    #print("codec_status=%s" % codecs)
    for name in ALL_CODECS:
        log("* %s : %s %s" % (name.ljust(20), str(name in codecs).ljust(10), codecs.get(name, "")))
    log("codecs versions:")
    for name, version in codec_versions.items():
        log("* %s : %s" % (name.ljust(20), version))


def get_codec_error(name):
    return codec_errors.get(name)

def get_codec(name):
    load_codecs()
    return codecs.get(name)

def get_codec_version(name):
    load_codecs()
    return codec_versions.get(name)

def has_codec(name):
    load_codecs()
    return name in codecs

OLD_ENCODING_NAMES_TO_NEW = {"x264" : "h264", "vpx" : "vp8"}
ALL_OLD_ENCODING_NAMES_TO_NEW = {"x264" : "h264", "vpx" : "vp8", "rgb24" : "rgb"}

ALL_CODECS = "PIL", "enc_vpx", "dec_vpx", "enc_x264", "enc_x265", "nvenc3", "nvenc4", "nvenc5", \
            "csc_swscale", "csc_cython", "csc_opencl", \
            "dec_avcodec2", \
            "enc_webp", \
            "dec_webp"

#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERED_ENCODING_ORDER = ["h264", "vp9", "vp8", "png", "png/P", "png/L", "webp", "rgb", "rgb24", "rgb32", "jpeg", "h265"]
#encoding order for edges (usually one pixel high or wide):
EDGE_ENCODING_ORDER = ["rgb24", "rgb32", "jpeg", "png", "webp", "png/P", "png/L", "rgb"]

from xpra.net import compression
RGB_COMP_OPTIONS  = ["Raw RGB"]
if compression.get_enabled_compressors():
    RGB_COMP_OPTIONS  += ["/".join(compression.get_enabled_compressors())]

ENCODINGS_TO_NAME = {
      "h264"    : "H.264",
      "h265"    : "H.265",
      "vp8"     : "VP8",
      "vp9"     : "VP9",
      "png"     : "PNG (24/32bpp)",
      "png/P"   : "PNG (8bpp colour)",
      "png/L"   : "PNG (8bpp grayscale)",
      "webp"    : "WebP",
      "jpeg"    : "JPEG",
      "rgb"     : " + ".join(RGB_COMP_OPTIONS) + " (24/32bpp)",
    }

ENCODINGS_HELP = {
      "h264"    : "H.264 video codec",
      "h265"    : "H.265 (HEVC) video codec (slow and buggy - do not use!)",
      "vp8"     : "VP8 video codec",
      "vp9"     : "VP9 video codec",
      "png"     : "Portable Network Graphics (lossless, 24bpp or 32bpp for transparency)",
      "png/P"   : "Portable Network Graphics (lossy, 8bpp colour)",
      "png/L"   : "Portable Network Graphics (lossy, 8bpp grayscale)",
      "webp"    : "WebP compression (lossless or lossy)",
      "jpeg"    : "JPEG lossy compression",
      "rgb"     : "Raw RGB pixels, lossless, compressed using %s (24bpp or 32bpp for transparency)" % (" or ".join(compression.get_enabled_compressors())),
      }

HELP_ORDER = ("h264", "h265", "vp8", "vp9", "png", "png/P", "png/L", "webp", "rgb", "jpeg")

#those are currently so useless that we don't want the user to select them by mistake
PROBLEMATIC_ENCODINGS = ("h265", )


def encodings_help(encodings):
    h = []
    for e in HELP_ORDER:
        if e in encodings:
            h.append(encoding_help(e))
    return h

def encoding_help(encoding):
    ehelp = ENCODINGS_HELP.get(encoding, "")
    return encoding.ljust(12) + ehelp



def main():
    from xpra.platform import init, clean
    try:
        init("Loader", "Encoding Info")
        verbose = "-v" in sys.argv or "--verbose" in sys.argv
        if verbose:
            log.enable_debug()

        load_codecs()
        print("codecs and csc modules found:")
        #print("codec_status=%s" % codecs)
        for name in ALL_CODECS:
            mod = codecs.get(name, "")
            f = mod
            if mod and hasattr(mod, "__file__"):
                f = mod.__file__
                if f.startswith(os.getcwd()):
                    f = f[len(os.getcwd()):]
                    if f.startswith(os.path.sep):
                        f = f[1:]
            print("* %s : %s" % (name.ljust(20), f))
            if mod and verbose:
                try:
                    if name=="PIL":
                        #special case for PIL which can be used for both encoding and decoding:
                        from xpra.codecs.codec_constants import get_PIL_encodings, get_PIL_decodings
                        e = get_PIL_encodings(mod)
                        print("                         ENCODE: %s" % ", ".join(e))
                        d = get_PIL_decodings(mod)
                        print("                         DECODE: %s" % ", ".join(d))
                    elif name.find("csc")>=0:
                        cs = list(mod.get_input_colorspaces())
                        for c in list(cs):
                            cs += list(mod.get_output_colorspaces(c))
                        print("                         %s" % ", ".join(list(set(cs))))
                    elif name.find("enc")>=0 or name.find("dec")>=0:
                        encodings = mod.get_encodings()
                        print("                         %s" % ", ".join(encodings))
                    try:
                        i = mod.get_info()
                        print("                         %s" % i)
                    except:
                        pass
                except Exception as e:
                    print("error getting extra information on %s: %s" % (name, e))
        print("")
        print("codecs versions:")
        def pver(v):
            if type(v)==tuple:
                return ".".join([str(x) for x in v])
            elif type(v) in (str, unicode) and v.startswith("v"):
                return v[1:]
            return str(v)
        for name in sorted(codec_versions.keys()):
            version = codec_versions[name]
            print("* %s : %s" % (name.ljust(20), pver(version)))
    finally:
        #this will wait for input on win32:
        clean()

if __name__ == "__main__":
    main()
