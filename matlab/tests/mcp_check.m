function r = mcp_check(name, passed, detail)
% MCP_CHECK  构造一条测试记录。所有套件返回同一结构的数组。
if nargin < 3
    detail = '';
end
r = struct('name', name, 'passed', logical(passed), 'detail', char(detail));
end
