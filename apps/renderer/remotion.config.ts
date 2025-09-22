// apps/renderer/remotion.config.ts
import {Config} from '@remotion/cli/config';
import os from 'os';

Config.setPublicDir('public');
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setConcurrency(Math.max(1, os.cpus().length - 1));
