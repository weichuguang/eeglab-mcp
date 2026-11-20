function run_all_tests(out_file)
% RUN_ALL_TESTS  运行全部 MATLAB 原生测试，写出 JSON 摘要。
%
%   matlab -batch "addpath('/path/to/eeglab-mcp/matlab'); run_all_tests('out.json')"
%
%   测试直接调用真实的 EEGLAB 函数与真实的 detect_units，不使用替身；
%   任一检查失败会让 MATLAB 以非零状态退出，同时保留 JSON 供解析。

if nargin < 1 || isempty(out_file)
    out_file = fullfile(tempdir, 'eeglab_mcp_matlab_tests.json');
end

here = fileparts(mfilename('fullpath'));
addpath(fileparts(here));   % matlab/
addpath(here);              % matlab/tests/

root = getenv('EEGLAB_ROOT');
if isempty(root)
    error('EEGLAB_MCP:NoRoot', 'Set EEGLAB_ROOT to your EEGLAB installation.');
end
if exist(root, 'dir') ~= 7
    error('EEGLAB_MCP:NoRoot', 'EEGLAB root not found: %s', root);
end
addpath(genpath(fullfile(root, 'functions')));

suites = {'test_core_functions', 'test_synthetic_erp', 'test_unit_detection', ...
          'test_plugin_presence', 'test_sample_dataset', 'test_spectral'};

results = struct('name', {}, 'passed', {}, 'detail', {});
fprintf('\nEEGLAB-MCP MATLAB native tests (EEGLAB root: %s)\n', root);
fprintf('%s\n', repmat('-', 1, 72));

for k = 1:numel(suites)
    name = suites{k};
    t0 = tic;
    try
        r = feval(name);
    catch ME
        r = mcp_check([name ':crashed'], false, ME.message);
    end
    if isempty(r)
        r = mcp_check([name ':empty'], false, '套件没有返回任何检查');
    end
    elapsed = toc(t0);
    for j = 1:numel(r)
        fprintf('%-38s %s  %s\n', r(j).name, pass_mark(r(j).passed), r(j).detail);
    end
    fprintf('  -> %s: %d 项，用时 %.1f s\n\n', name, numel(r), elapsed);
    results = [results r]; %#ok<AGROW>
end

n_pass = sum([results.passed]);
n_fail = numel(results) - n_pass;
fprintf('%s\n', repmat('-', 1, 72));
fprintf('总计 %d 项：通过 %d，失败 %d\n', numel(results), n_pass, n_fail);

payload = struct();
payload.ok = (n_fail == 0);
payload.passed = n_pass;
payload.failed = n_fail;
payload.total = numel(results);
payload.eeglab_root = root;
payload.finished_utc = datestr(now, 'yyyy-mm-dd HH:MM:SS');
payload.tests = results;

fid = fopen(out_file, 'w', 'n', 'UTF-8');
if fid < 0
    error('EEGLAB_MCP:WriteFailed', 'Cannot write %s', out_file);
end
fwrite(fid, jsonencode(payload), 'char');
fclose(fid);
fprintf('结果已写入 %s\n', out_file);

if n_fail > 0
    error('EEGLAB_MCP:TestsFailed', '%d of %d MATLAB native tests failed', n_fail, numel(results));
end
end

function s = pass_mark(ok)
if ok
    s = 'PASS';
else
    s = 'FAIL';
end
end
