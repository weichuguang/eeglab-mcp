function results = test_unit_detection()
% TEST_UNIT_DETECTION  验证单位推断逻辑本身（matlab/detect_units.m）。
%
%   单位误判会让报告幅值相差百万倍，是最难从结果上察觉的错误之一。
%   因此这里直接对真实函数做三种输入的判定，而不是复制它的逻辑。

results = struct('name', {}, 'passed', {}, 'detail', {});

try
    EEG = make_synthetic_eeg(128, 8, 10, 'noise_amp', 2);   % 微伏量级
    [scale, unit] = detect_units(EEG);
    results(end + 1) = mcp_check('units:microvolt', strcmp(unit, 'uV') && scale == 1, ...
        sprintf('uV 数据 -> unit=%s scale=%g', unit, scale));
catch ME
    results(end + 1) = mcp_check('units:microvolt', false, ME.message);
end

try
    EEG = make_synthetic_eeg(128, 8, 10, 'noise_amp', 2);
    EEG.data = EEG.data / 1e6;                              % 改为伏特存储
    [scale, unit] = detect_units(EEG);
    results(end + 1) = mcp_check('units:volt', strcmp(unit, 'V') && scale == 1e6, ...
        sprintf('V 数据 -> unit=%s scale=%g', unit, scale));
catch ME
    results(end + 1) = mcp_check('units:volt', false, ME.message);
end

try
    EEG = make_synthetic_eeg(128, 8, 10, 'noise_amp', 2);
    EEG.data(:) = 0;                                        % 全零：无法判断
    [scale, unit] = detect_units(EEG);
    results(end + 1) = mcp_check('units:unknown', strcmp(unit, 'unknown') && scale == 1, ...
        sprintf('全零数据 -> unit=%s scale=%g', unit, scale));
catch ME
    results(end + 1) = mcp_check('units:unknown', false, ME.message);
end
end
