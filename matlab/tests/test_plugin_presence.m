function results = test_plugin_presence()
% TEST_PLUGIN_PRESENCE  检查方法配置声明依赖的插件是否真的可用。
%
%   门控里的 plugin_available 会读取同一组事实。插件缺失不是错误，
%   但必须被如实报告——否则调用者会以为 ASR 或 ICLabel 已经可用。

results = struct('name', {}, 'passed', {}, 'detail', {});

plugins = {
    'clean_rawdata', 'clean_asr',          'ASR 伪迹子空间重建'
    'ICLabel',       'pop_iclabel',        '成分自动分类（辅助判读）'
    'ERPLAB',        'pop_erplab_mainGUI', 'ERP 测量与统计'
    'BIOSIG',        'pop_biosig',         'EDF/BDF 等格式导入'
};

for k = 1:size(plugins, 1)
    name = plugins{k, 1};
    fn = plugins{k, 2};
    present = exist(fn, 'file') == 2;
    if present
        detail = sprintf('%s 可用（%s）', name, fn);
    else
        detail = sprintf('%s 未安装（未找到 %s）：依赖它的方法配置会被门控阻断', name, fn);
    end
    results(end + 1) = mcp_check(['plugin:' name], true, detail);
end
end
