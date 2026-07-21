# 🔒 安全配置指南

你的敏感信息已从代码中移除。现在需要在 GitHub Actions 中配置它们。

## 步骤 1：合并 PR（已完成）

1. 打开：https://github.com/DongpuLi/parks-canada-campsite-monitor/compare/main...fix/remove-sensitive-data
2. 点击 **"Create Pull Request"**
3. 查看更改（已移除敏感数据）
4. 点击 **"Merge pull request"** → **"Confirm merge"**

---

## 步骤 2：配置 GitHub Actions Variables

📍 去：`Settings → Secrets and variables → Actions → Variables`

创建以下 **Variables**（这些信息可以公开显示）：

| 变量名 | 值 | 示例 |
|--------|-----|--------|
| `MONITOR_ENABLED` | `true` 或 `false` | `true` |
| `PARKS_SEARCH_URL` | 完整的公园预订 URL | `https://www.pc.gc.ca/...` |
| `TARGET_SITES` | 逗号分隔的营地号 | `17,22,23,24,25` |
| `MONITOR_LABEL` | 可选：你的行程标签 | `Mkwesaqtuk/Cap-Rouge Sep 4–7` |

### 如何获取 PARKS_SEARCH_URL：
1. 打开 https://www.pc.gc.ca/
2. 搜索你的营地
3. 设置日期、人数、装备等
4. 点击"Search"后，**复制地址栏的 URL**

---

## 步骤 3：配置 GitHub Actions Secrets

📍 同一页面，点击 **"Secrets"** 标签

创建以下 **Secrets**（这些信息 GitHub 会加密存储）：

| 密钥名 | 说明 |
|--------|------|
| `SMTP_HOST` | 你的邮件服务器地址（如 `smtp.gmail.com`） |
| `SMTP_PORT` | 邮件服务器端口（如 `465` 或 `587`） |
| `SMTP_USERNAME` | 邮箱账号 |
| `SMTP_PASSWORD` | 邮箱密码或应用密码 |
| `ALERT_EMAIL` | 接收通知的邮箱 |
| `ALERT_FROM` | 发件人（通常与 SMTP_USERNAME 相同） |

### Gmail 示例配置：
```
SMTP_HOST: smtp.gmail.com
SMTP_PORT: 465
SMTP_USERNAME: your-email@gmail.com
SMTP_PASSWORD: [应用专用密码，不是账号密码]
ALERT_EMAIL: your-email@gmail.com
ALERT_FROM: your-email@gmail.com
```

💡 **重要**：Gmail 要求使用 [应用专用密码](https://support.google.com/accounts/answer/185833)，不能用账号密码。

---

## 步骤 4：测试配置

✅ 测试运行（无需等待定时任务）：

1. 去：https://github.com/DongpuLi/parks-canada-campsite-monitor/actions
2. 选择 **"Parks Canada campsite monitor"** workflow
3. 点击 **"Run workflow"**
4. 三个输入框都留空（会使用保存的 Variables 和 Secrets）
5. 点击 **"Run workflow"**
6. 检查运行结果和你的邮箱

---

## 步骤 5：启用定时监控

配置完成后，工作流会在以下情况运行：

- **定时运行**：每小时检查一次（`MONITOR_ENABLED = true`）
- **手动运行**：随时点击 "Run workflow" 测试
- **可用时发送邮件**：如果你指定的营地有空位，会立即通知

---

## 安全检查清单

- ✅ `config.json` 中的敏感数据已移除
- ✅ `.gitignore` 已添加，防止 `config.json` 被提交
- ✅ 所有配置现在存储在 GitHub Actions Secrets（加密）
- ✅ 代码库中不再有邮箱、日期、位置号等私密信息
- ✅ 即使仓库是 public，也不会暴露你的预订计划

---

## 常见问题

**Q: 为什么邮件没有发送？**
- A: 检查 `SMTP_*` 和 `ALERT_*` 的 Secrets 配置
- 检查 GitHub Actions 运行日志了解更多细节

**Q: 如何暂停监控？**
- A: 将 `MONITOR_ENABLED` 改为 `false`

**Q: 可以监控多个营地吗？**
- A: 可以！在 `PARKS_SEARCH_URL` 中改变营地，然后点击 "Run workflow" 手动运行。或者创建新的 workflow 文件处理多个营地。

---

## 后续维护

如果你要监控新的行程：
1. 更新 `PARKS_SEARCH_URL` 变量
2. 更新 `TARGET_SITES` 变量
3. 更新 `MONITOR_LABEL` 变量（可选）
4. 无需改动代码！
