# Issue2PR

把仓库里的一个 issue，自动变成一份能让测试通过的补丁，并开成 PR。

> **状态：开发中，还不能用。** 目前仓库里只有 `action.yml`（接口定义）。
> 下面「用法」写的是目标形态，不是现在能跑的东西。

## 它是什么

一个 GitHub Action，装在**你自己的仓库**里。有人开 issue，它就：

1. 读 issue 正文
2. 在仓库里定位相关代码（当前策略：文本搜索）
3. 改代码
4. 跑仓库自带的测试
5. 全绿 → 开 PR；没修好 → 在 issue 下评论说明卡在哪

## 用法

在目标仓库里加 `.github/workflows/issue2pr.yml`：

```yaml
name: Issue2PR
on:
  issues:
    types: [opened]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  fix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: wudi091/Issue2PR@main
        with:
          api_key: ${{ secrets.DEEPSEEK_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

`DEEPSEEK_API_KEY` 要自己在仓库的 Settings → Secrets 里加。
`github_token` 不用配，GitHub 每次运行自动提供。

## 输入

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_key` | 是 | — | 模型 API key |
| `github_token` | 是 | — | 传 `${{ secrets.GITHUB_TOKEN }}` |
| `model` | 否 | `deepseek-chat` | 模型名 |
| `base_url` | 否 | `https://api.deepseek.com` | 兼容 OpenAI 格式即可换供应商 |
| `max_steps` | 否 | `20` | 最大工具调用步数，同时也是成本上限 |
| `locator` | 否 | `keyword` | 代码定位策略 |

## 输出

| 参数 | 说明 |
| --- | --- |
| `status` | `resolved` / `failed` |
| `pr_url` | 成功时开出的 PR 链接 |

## 设计取舍

这几个是已经定下来的决定，改起来代价大，先记在这里：

- **不限语言，只做文本搜索定位。** 调用图定位必须按语言写解析器，跟「任意仓库」冲突。定位策略留了开关，以后要加就加语义检索——那个同样不挑语言。
- **PR 以 `github-actions[bot]` 身份提交。** 代价是用 `GITHUB_TOKEN` 开的 PR **不会触发目标仓库自己的 CI**（GitHub 防递归的设定）。想触发就得换 PAT。
- **token 在容器里。** 因为 PR 由容器自己开。`GITHUB_TOKEN` 权限仅限当前仓库、跑完即失效，所以损失有上限；但目标仓库的依赖若夹带恶意代码，理论上能读走它。

## 开发

代码还没开始写。目前只有：

```
action.yml     Action 的输入输出接口
```
