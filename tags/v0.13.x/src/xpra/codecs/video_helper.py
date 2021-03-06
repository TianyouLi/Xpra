#!/usr/bin/env python
# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from threading import Lock
from xpra.log import Logger
log = Logger("codec", "video")

from xpra.codecs.loader import get_codec, get_codec_error, load_codecs


#the codec loader uses the names...
#but we need the module name to be able to probe without loading the codec:
CODEC_TO_MODULE = {"vpx"        : "vpx",
                   "x264"       : "enc_x264",
                   "x265"       : "enc_x265",
                   "nvenc"      : "nvenc",
                   "swscale"    : "csc_swscale",
                   "cython"     : "csc_cython",
                   "opencl"     : "csc_opencl",
                   "avcodec"    : "dec_avcodec",
                   "avcodec2"   : "dec_avcodec2"}

def has_codec_module(module_name):
    top_module = "xpra.codecs.%s" % module_name
    try:
        __import__(top_module, {}, {}, [])
        log("codec module %s is installed", module_name)
        return True
    except Exception, e:
        log("codec module %s cannot be loaded: %s", module_name, e)
        return False

def try_import_modules(codec_names):
    names = []
    for codec_name in codec_names:
        module_name = CODEC_TO_MODULE[codec_name]
        if has_codec_module(module_name):
            names.append(codec_name)
    return names

#all the codecs we know about:
#try to import the module that contains them (cheap check):
ALL_VIDEO_ENCODER_OPTIONS = try_import_modules(["x264", "vpx", "x265", "nvenc"])
ALL_CSC_MODULE_OPTIONS = try_import_modules(["swscale", "cython", "opencl"])
NO_GFX_CSC_OPTIONS = [x for x in ALL_CSC_MODULE_OPTIONS if x not in ("opencl", )]
ALL_VIDEO_DECODER_OPTIONS = try_import_modules(["avcodec", "avcodec2", "vpx"])

PREFERRED_ENCODER_ORDER = ["nvenc", "x264", "vpx", "x265"]
PREFERRED_DECODER_ORDER = ["avcodec", "avcodec2", "vpx"]
log("video_helper: ALL_VIDEO_ENCODER_OPTIONS=%s", ALL_VIDEO_ENCODER_OPTIONS)
log("video_helper: ALL_CSC_MODULE_OPTIONS=%s", ALL_CSC_MODULE_OPTIONS)
log("video_helper: NO_GFX_CSC_OPTIONS=%s", NO_GFX_CSC_OPTIONS)
log("video_helper: ALL_VIDEO_DECODER_OPTIONS=%s", ALL_VIDEO_DECODER_OPTIONS)
#for client side, using the gfx card for csc is a bit silly:
#use it for OpenGL or don't use it at all
#on top of that, there are compatibility problems with gtk at times: OpenCL AMD and TLS don't mix well


def get_encoder_module_name(x):
        if x.find("enc")>=0:
            return x            #ie: "nvenc" or "enc_vpx"
        return "enc_"+x         #ie: "enc_x264"

def get_decoder_module_name(x):
        return "dec_"+x         #ie: "dec_vpx"

def get_csc_module_name(x):
    return "csc_"+x             #ie: "csc_swscale"



def get_DEFAULT_VIDEO_ENCODERS():
    """ returns all the video encoders installed """
    encoders = []
    for x in list(ALL_VIDEO_ENCODER_OPTIONS):
        mod = get_encoder_module_name(x)
        c = get_codec(mod)
        if c:
            encoders.append(x)
    return encoders

def get_DEFAULT_CSC_MODULES():
    """ returns all the csc modules installed """
    csc = []
    for x in list(ALL_CSC_MODULE_OPTIONS):
        mod = get_csc_module_name(x)
        c = get_codec(mod)
        if c:
            csc.append(x)
    return csc

def get_DEFAULT_VIDEO_DECODERS():
    """ returns all the video decoders installed """
    decoders = []
    for x in list(ALL_VIDEO_DECODER_OPTIONS):
        mod = get_decoder_module_name(x)
        c = get_codec(mod)
        if c:
            decoders.append(x)
    return decoders


class VideoHelper(object):
    """
        This class is a bit like a registry of known encoders, csc modules and decoders.
        The main instance, obtained by calling getVideoHelper, can be initialized
        by the main class, using the command line arguments.
        We can also clone it to modify it (used by per client proxy encoders)
    """

    def __init__(self, vencspecs={}, cscspecs={}, vdecspecs={}, init=False):
        self._video_encoder_specs = vencspecs
        self._csc_encoder_specs = cscspecs
        self._video_decoder_specs = vdecspecs
        self.video_encoders = []
        self.csc_modules = []
        self.video_decoders = []

        self._cleanup_modules = []

        #bits needed to ensure we can initialize just once
        #even when called from multiple threads:
        self._initialized = init
        self._lock = Lock()

    def set_modules(self, video_encoders=[], csc_modules=[], video_decoders=[]):
        assert not self._initialized, "too late to set modules, the helper is already initialized!"
        self.video_encoders = [x for x in video_encoders if x in ALL_VIDEO_ENCODER_OPTIONS]
        self.csc_modules    = [x for x in csc_modules    if x in ALL_CSC_MODULE_OPTIONS]
        self.video_decoders = [x for x in video_decoders if x in ALL_VIDEO_DECODER_OPTIONS]
        log("VideoHelper.set_modules(%s, %s, %s) video encoders=%s, csc=%s, video decoders=%s",
            video_encoders, csc_modules, video_decoders, self.video_encoders, self.csc_modules, self.video_decoders)

    def cleanup(self):
        try:
            self._lock.acquire()
            #check again with lock held (in case of race):
            if not self._initialized:
                return
            for module in self._cleanup_modules:
                try:
                    module.cleanup_module()
                except:
                    log.error("error cleaning up %s", module, exc_info=True)
            self._cleanup_modules = []
            self._video_encoder_specs = {}
            self._csc_encoder_specs = {}
            self._video_decoder_specs = {}
            self.video_encoders = []
            self.csc_modules = []
            self.video_decoders = []
            self._initialized = False
        finally:
            self._lock.release()

    def clone(self):
        if not self._initialized:
            self.init()
        #manual deep-ish copy: make new dictionaries and lists,
        #but keep the same codec specs:
        def deepish_clone_dict(indict):
            outd = {}
            for enc, d in indict.items():
                for ifmt, l in d.items():
                    for v in l:
                        outd.setdefault(enc, {}).setdefault(ifmt, []).append(v)
            return outd
        ves = deepish_clone_dict(self._video_encoder_specs)
        ces = deepish_clone_dict(self._csc_encoder_specs)
        vds = deepish_clone_dict(self._video_decoder_specs)
        return VideoHelper(ves, ces, vds, True)

    def get_info(self):
        d = {}
        for encoding, encoder_specs in self._video_encoder_specs.items():
            for in_csc, specs in encoder_specs.items():
                for spec in specs:
                    d.setdefault("encoding."+in_csc+"_to_"+encoding, []).append(spec.codec_type)
        for in_csc, specs in self._csc_encoder_specs.items():
            for out_csc, specs in specs.items():
                d["csc."+in_csc+"_to_"+out_csc] = [spec.codec_type for spec in specs]
        for encoding, decoder_specs in self._video_decoder_specs.items():
            for out_csc, decoders in decoder_specs.items():
                for decoder in decoders:
                    decoder_name, _ = decoder
                    d.setdefault("decoding."+encoding+"_to_"+out_csc, []).append(decoder_name)
        return d

    def init(self):
        log("VideoHelper.init()")
        load_codecs()
        try:
            self._lock.acquire()
            #check again with lock held (in case of race):
            log("VideoHelper.init() initialized=%s", self._initialized)
            if self._initialized:
                return
            self.init_video_encoders_options()
            self.init_csc_options()
            self.init_video_decoders_options()
            self._initialized = True
        finally:
            self._lock.release()
        log("VideoHelper.init() done")

    def get_encodings(self):
        return self._video_encoder_specs.keys()

    def get_decodings(self):
        return self._video_decoder_specs.keys()

    def get_csc_inputs(self):
        return self._csc_encoder_specs.keys()


    def get_encoder_specs(self, encoding):
        return self._video_encoder_specs.get(encoding, {})

    def get_csc_specs(self, src_format):
        return self._csc_encoder_specs.get(src_format, {})

    def get_decoder_specs(self, encoding):
        return self._video_decoder_specs.get(encoding, {})


    def init_video_encoders_options(self):
        log("init_video_encoders_options() will try video encoders: %s", self.video_encoders)
        for x in self.video_encoders:
            try:
                mod = get_encoder_module_name(x)
                self.init_video_encoder_option(mod)
            except:
                log.warn("init_video_encoders_options() cannot add %s encoder", x, exc_info=True)
        log("init_video_encoders_options() video encoder specs: %s", self._video_encoder_specs)

    def init_video_encoder_option(self, encoder_name):
        encoder_module = get_codec(encoder_name)
        log("init_video_encoder_option(%s) module=%s", encoder_name, encoder_module)
        if not encoder_module:
            log.warn("video encoder %s could not be loaded: %s", encoder_name, get_codec_error(encoder_name))
            return
        encoder_type = encoder_module.get_type()
        try:
            encoder_module.init_module()
            self._cleanup_modules.append(encoder_module)
        except Exception, e:
            log.warn("cannot use %s module %s: %s", encoder_type, encoder_module, e, exc_info=True)
            return
        colorspaces = encoder_module.get_input_colorspaces()
        log("init_video_encoder_option(%s) %s input colorspaces=%s", encoder_module, encoder_type, colorspaces)
        encodings = encoder_module.get_encodings()
        log("init_video_encoder_option(%s) %s encodings=%s", encoder_module, encoder_type, encodings)
        for encoding in encodings:
            #we assume that all encodings support all colorspaces here...
            #which may not be the case in the future!
            for colorspace in colorspaces:
                spec = encoder_module.get_spec(encoding, colorspace)
                self.add_encoder_spec(encoding, colorspace, spec)

    def add_encoder_spec(self, encoding, colorspace, spec):
        self._video_encoder_specs.setdefault(encoding, {}).setdefault(colorspace, []).append(spec)


    def init_csc_options(self):
        log("init_csc_options() will try csc modules: %s", self.csc_modules)
        for x in self.csc_modules:
            try:
                mod = get_csc_module_name(x)
                self.init_csc_option(mod)
            except:
                log.warn("init_csc_options() cannot add %s csc", x, exc_info=True)
        log("init_csc_options() csc specs: %s", self._csc_encoder_specs)
        for src_format, d in sorted(self._csc_encoder_specs.items()):
            log("%s - %s options:", src_format, len(d))
            for dst_format, specs in sorted(d.items()):
                log(" * %s via: %s", dst_format, sorted(list(specs), key=lambda spec: spec.codec_type))

    def init_csc_option(self, csc_name):
        csc_module = get_codec(csc_name)
        log("init_csc_option(%s) module=%s", csc_name, csc_module)
        if csc_module is None:
            log.warn("csc module %s could not be loaded: %s", csc_name, get_codec_error(csc_name))
            return
        csc_type = csc_module.get_type()
        try:
            csc_module.init_module()
            self._cleanup_modules.append(csc_module)
        except Exception, e:
            log.warn("cannot use %s module %s: %s", csc_type, csc_module, e)
            return
        in_cscs = csc_module.get_input_colorspaces()
        for in_csc in in_cscs:
            out_cscs = csc_module.get_output_colorspaces(in_csc)
            log("init_csc_option(..) %s.get_output_colorspaces(%s)=%s", csc_module.get_type(), in_csc, out_cscs)
            for out_csc in out_cscs:
                spec = csc_module.get_spec(in_csc, out_csc)
                self.add_csc_spec(in_csc, out_csc, spec)

    def add_csc_spec(self, in_csc, out_csc, spec):
        self._csc_encoder_specs.setdefault(in_csc, {}).setdefault(out_csc, []).append(spec)


    def init_video_decoders_options(self):
        log("init_video_decoders_options() will try video decoders: %s", self.video_decoders)
        for x in self.video_decoders:
            try:
                mod = get_decoder_module_name(x)
                self.init_video_decoder_option(mod)
            except:
                log.warn("init_video_decoders_options() cannot add %s decoder", x, exc_info=True)
        log("init_video_decoders_options() video decoder specs: %s", self._video_decoder_specs)

    def init_video_decoder_option(self, decoder_name):
        decoder_module = get_codec(decoder_name)
        log("init_video_decoder_option(%s) module=%s", decoder_name, decoder_module)
        if not decoder_module:
            log.warn("video decoder %s could not be loaded: %s", decoder_name, get_codec_error(decoder_name))
            return
        encoder_type = decoder_module.get_type()
        try:
            decoder_module.init_module()
            self._cleanup_modules.append(decoder_module)
        except Exception, e:
            log.warn("cannot use %s module %s: %s", encoder_type, decoder_module, e, exc_info=True)
            return
        encodings = decoder_module.get_encodings()
        log("init_video_decoder_option(%s) %s encodings=%s", decoder_module, encoder_type, encodings)
        for encoding in encodings:
            colorspaces = decoder_module.get_input_colorspaces(encoding)
            log("init_video_decoder_option(%s) %s input colorspaces for %s: %s", decoder_module, encoder_type, encoding, colorspaces)
            for colorspace in colorspaces:
                output_colorspace = decoder_module.get_output_colorspace(encoding, colorspace)
                log("init_video_decoder_option(%s) get_output_colorspace(%s, %s)=%s", decoder_name, encoding, colorspace, output_colorspace)
                try:
                    assert decoder_module.Decoder
                    self.add_decoder(encoding, colorspace, decoder_name, decoder_module)
                except Exception, e:
                    log.warn("failed to add decoder %s: %s", decoder_module, e)

    def add_decoder(self, encoding, colorspace, decoder_name, decoder_module):
        self._video_decoder_specs.setdefault(encoding, {}).setdefault(colorspace, []).append((decoder_name, decoder_module))


    def get_server_full_csc_modes(self, *client_supported_csc_modes):
        """ given a list of CSC modes the client can handle,
            returns the CSC modes per encoding that the server can encode with.
            (taking into account the decoder's actual output colorspace for each encoding)
        """
        full_csc_modes = {}
        for encoding, encoding_specs in self._video_decoder_specs.items():
            assert encoding_specs is not None
            for colorspace, decoder_specs in sorted(encoding_specs.items()):
                for decoder_name, decoder_module in decoder_specs:
                    log("found decoder %s for %s with %s mode", decoder_name, encoding, colorspace)
                    #figure out the actual output colorspace:
                    output_colorspace = decoder_module.get_output_colorspace(encoding, colorspace)
                    if output_colorspace in client_supported_csc_modes:
                        encoding_colorspaces = full_csc_modes.setdefault(encoding, [])
                        if colorspace not in encoding_colorspaces:
                            encoding_colorspaces.append(colorspace)
        log("get_client_full_csc_modes(%s)=%s", client_supported_csc_modes, full_csc_modes)
        return full_csc_modes


    def get_server_full_csc_modes_for_rgb(self, *target_rgb_modes):
        """ given a list of RGB modes the client can handle,
            returns the CSC modes per encoding that the server can encode with,
            this will include the RGB modes themselves too.
        """
        log("get_server_full_csc_modes_for_rgb%s", target_rgb_modes)
        supported_csc_modes = list(target_rgb_modes)
        for src_format, specs in self._csc_encoder_specs.items():
            for dst_format, csc_specs in specs.items():
                if dst_format in target_rgb_modes and len(csc_specs)>0:
                    supported_csc_modes.append(src_format)
                    break
        supported_csc_modes = sorted(supported_csc_modes)
        return self.get_server_full_csc_modes(*supported_csc_modes)


instance = VideoHelper()
def getVideoHelper():
    global instance
    return instance



def main():
    from xpra.codecs.loader import log as loader_log
    loader_log.enable_debug()
    if "-v" in sys.argv or "--verbose" in sys.argv:
        log.enable_debug()
    vh = getVideoHelper()
    vh.set_modules(ALL_VIDEO_ENCODER_OPTIONS, ALL_CSC_MODULE_OPTIONS, ALL_VIDEO_DECODER_OPTIONS)
    vh.init()
    log.info("VideoHelper.get_info():")
    info = vh.get_info()
    for k in sorted(info.keys()):
        v = info.get(k)
        log.info("%s=%s", k, v)


if __name__ == "__main__":
    main()
