# Issue2PR

把仓库里的一个 issue，自动变成一份能让测试通过的补丁，并开成 PR。

> **状态：能用了。** 已经在一个真实仓库上端到端跑通：
> 开 issue → Actions 拉起容器 → Agent 定位 / 改码 / 跑测试 → 自动开 PR。
> 实例：<https://github.com/wudi091/issue2pr-sandbox/pull/7>

## 它是什么

一个 GitHub Action，装在**你自己的仓库**里。有人开 issue，它就：

1. 读 issue 正文
2. 在仓库里定位相关代码（当前策略：文本搜索）
3. 改代码
4. 跑仓库自带的测试
5. 全绿 → 开 PR；没修好 → 在 issue 下评论说明卡在哪

## 用法

### 1. 先打开这个开关

**Settings → Actions → General → Workflow permissions →
☑ Allow GitHub Actions to create and approve pull requests**

不开的话 PR 那一步会拿到 403：

```
GitHub Actions is not permitted to create or approve pull requests
```

这是 GitHub 的默认安全设置（防止 workflow 自己批准自己的 PR），不是本项目的要求，
但本项目靠它开 PR，所以必须开。

### 2. 加 workflow

在目标仓库里建 `.github/workflows/issue2pr.yml`：

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
          api_key: ${{ secrets.MODEL_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

### 3. 加 secret

`api_key` 对应的那个 secret 要自己在 **Settings → Secrets and variables → Actions** 里加。
`github_token` 不用配，GitHub 每次运行自动提供。

> 公开仓库建议再加一行守卫，否则任何人都能开个 issue 让别人替你烧模型额度：
>
> ```yaml
>     if: github.event.issue.user.login == github.repository_owner
> ```

### 模型端点在内网 / tailnet 里的话

托管 runner 跑在 GitHub 的机房，够不着你的内网地址。让 runner 临时加入 tailnet：

```yaml
      - name: 加入 tailnet
        uses: tailscale/github-action@v4
        with:
          authkey: ${{ secrets.TS_AUTHKEY }}
          ping: 100.x.y.z
```

Auth key 在 <https://login.tailscale.com/admin/settings/keys> 建，**必须勾 Reusable**
（不勾的话用一次就作废），建议勾 Ephemeral（CI 节点跑完自动消失）。
节点是临时加入、跑完销毁的。

## 输入

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_key` | 是 | — | 模型 API key |
| `github_token` | 是 | — | 传 `${{ secrets.GITHUB_TOKEN }}` |
| `model` | 否 | `deepseek-chat` | 模型名 |
| `base_url` | 否 | `https://api.deepseek.com` | 兼容 OpenAI 格式即可换供应商 |
| `max_steps` | 否 | `20` | 最多几次模型调用，同时也是成本上限 |
| `locator` | 否 | `keyword` | 代码定位策略。**预留，还没接上** |

## 输出

| 参数 | 说明 |
| --- | --- |
| `status` | `resolved` / `failed` / `budget_exhausted` |
| `pr_url` | 成功时开出的 PR 链接 |

## 设计取舍

这几个是已经定下来的决定，改起来代价大，先记在这里：

- **「修好了」由模型自己宣布，没有独立验证。** 自动探测测试命令不现实（语言、框架太多），
  所以 Action 直接信 `status == resolved`。代价是模型谎报就会开出坏 PR。
  缓解：PR 描述里带着完整轨迹（每条命令 + 它看到的输出），并且正文里明写「请人工 review」。
  以后可以加一步「Action 自己重跑一遍测试」。
- **不限语言，只做文本搜索定位。** 调用图定位必须按语言写解析器，跟「任意仓库」冲突。
  定位策略留了开关，以后要加就加语义检索——那个同样不挑语言。
- **PR 以 `github-actions[bot]` 身份提交。** 代价是用 `GITHUB_TOKEN` 开的 PR
  **不会触发目标仓库自己的 CI**（GitHub 防递归的设定）。想触发就得换 PAT。
- **token 在容器里。** 因为 PR 由容器自己开。`GITHUB_TOKEN` 权限仅限当前仓库、跑完即失效，
  所以损失有上限；但目标仓库的依赖若夹带恶意代码，理论上能读走它。
- **镜像里没有测试框架。** 目标仓库要什么测试工具，Agent 得自己装（容器有网）。
  慢，且依赖网络。以后要么预装常见的，要么加一个「装依赖」的输入。

## 开发

分六层，依赖方向单向不成环：

```
issue2pr/
  result.py            契约层     状态取值 / TaskDone / RunResult
  prompt.py            提示词层   SYSTEM_PROMPT
  model.py             模型层     客户端 + 一次调用
  env/
    __init__.py        环境层契约  Result / EnvError / Env 协议（不碰磁盘）
    local.py           环境层实现  真实磁盘 + 真实子进程
  tools/
    __init__.py        工具汇总    build(env) 一键装配
    dispatch.py        机制        绑定校验、执行一次调用
    bash.py            bash 工具   模型唯一的能力入口
  loop.py              调度层     AgentLoop
  action/              集成层     GitHub Action 的输入输出
    event.py           事件负载 → Issue（缺字段直接炸，不静默兜底）
    outputs.py         结论 → $GITHUB_OUTPUT
    git.py             开分支、提交、push
    api.py             开 PR、评论 issue
    report.py          轨迹 → PR 描述 / issue 评论
    publish.py         收口：什么情况开 PR、什么情况只评论
  __main__.py          组装根     全项目只有这里 import 具体实现
```

跑测试：

```bash
python -m pytest tests
```

本地拿一个 issue 试跑（不碰 GitHub）：

```bash
export INPUT_API_KEY=...
python -m issue2pr --repo /path/to/repo --issue "issue 正文"
```

本地也可以完整走一遍 Action 模式（会真的 push 分支、开 PR）：

```bash
export INPUT_API_KEY=... INPUT_GITHUB_TOKEN=... GITHUB_EVENT_PATH=/path/to/event.json
python -m issue2pr --repo /path/to/clone
```
