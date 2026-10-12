FROM python:3.12-slim

# git 是必需品：建分支、提交、push 全走它
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 工作区是挂进来的 /github/workspace，属主跟容器里的 root 不一致，
# git 会拒绝操作（detected dubious ownership）。容器是一次性的，放开值得。
#
# 必须用 --system，不能用 --global：构建时 HOME=/root，写进去的是 /root/.gitconfig，
# 而 GitHub 跑容器动作时把 HOME 设成 /github/home —— 运行时 git 根本不读那一份。
# system 配置落在 /etc/gitconfig，跟 HOME 无关。
RUN git config --system --add safe.directory '*'

WORKDIR /issue2pr

# 只拷装包需要的，tests 和 .git 不进镜像
COPY pyproject.toml README.md ./
COPY issue2pr ./issue2pr
RUN pip install --no-cache-dir .

# action.yml 的 runs.image 用这个 ENTRYPOINT；
# 输入走 INPUT_* 环境变量，issue 正文走 $GITHUB_EVENT_PATH
ENTRYPOINT ["python", "-m", "issue2pr"]
