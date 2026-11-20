function [scale, unit] = detect_units(EEG)
% DETECT_UNITS  推断 EEG.data 的物理单位。
%
%   EEGLAB 惯例为微伏，但部分采集或导出流程把数据存成伏特。
%   返回换算到微伏的比例因子与单位标签（诚实标注，供结果说明）。
%
%   独立成文件而不是 run_job.m 的子函数，是为了让 MATLAB 原生测试
%   能直接验证这段判断逻辑本身，而不是验证它的副本。

v = abs(double(EEG.data(:)));
v = v(isfinite(v));
if isempty(v) || median(v) == 0
    scale = 1; unit = 'unknown';
elseif median(v) < 1e-3
    scale = 1e6; unit = 'V';          % 伏特 -> 微伏
else
    scale = 1;   unit = 'uV';         % 已是微伏
end
end
