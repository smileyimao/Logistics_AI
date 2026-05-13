# 运单助手 — 项目进度 Roadmap
**更新时间：2026-05-13**

---

## ✅ 已完成

### 基础设施
- [x] 腾讯云香港服务器（43.129.175.80，¥38/月）
- [x] 防火墙配置（80 / 443 / 5001 端口开放）
- [x] Python 虚拟环境 + 所有依赖安装
- [x] nginx 安装并配置反向代理
- [x] SSL 证书安装（Let's Encrypt，有效至2026-08-10，自动续期）
- [x] **HTTPS 正式上线：https://ai.xcstlogistics.com** ✅

### 域名
- [x] xcstlogistics.com 注册（腾讯云，雄楚速通公司主体，¥83/年）
- [x] DNS 解析：ai.xcstlogistics.com → 43.129.175.80

### 微信公众号（V1）
- [x] 公众号「慢富论」配置消息推送（URL / Token）
- [x] server.py 公众号版部署到云服务器并运行
- [x] 微信验证通过，已收到真实消息

### 企业微信应用
- [x] 创建自建应用「运单助手」（AgentId: 1000002）
- [x] 获取所有凭证（CorpID / AgentID / Secret / Token / EncodingAESKey）
- [x] 应用 logo 制作

### AI 能力
- [x] 阿里云百炼 API Key（Qwen-VL 图片识别）
- [x] server.py 接入 Qwen-VL

### 产品规划
- [x] V1/V2 流程说明文档 + 海报
- [x] 业务规划 Dashboard

---

## 🚧 进行中

### 企业微信接收消息配置
- [ ] 填入 https://ai.xcstlogistics.com/wecom 并验证
- **状态**：SSL 已配好，等明威醒来登录后台测试
- **结果预期**：能过 → 直接上V2；不能过 → 走ICP备案

### 实名模板审核
- **状态**：已提交，等待审核（1-3天）

---

## ⏳ 待完成

### 明威醒来后（今天）
- [ ] 登录企业微信后台，填入 https://ai.xcstlogistics.com/wecom
- [ ] 测试域名能否通过企业微信实体验证
- [ ] 用公众号发真实运单图片，测试识别效果
- [ ] 验证导出Excel功能完整流程

### 演示
- [ ] 识别准确率达到可演示水平
- [ ] 给明威演示：发图 → 识别 → 导出
- [ ] 收集反馈，调整识别字段

### 如果企业微信验证不通过（备案路线）
- [ ] 向明威收集营业执照 + 法人身份证
- [ ] 腾讯云提交 ICP 备案（需另购大陆服务器）
- [ ] 等待审核（7-20工作日）

### 让服务器保持运行（重要）
- [ ] 配置 systemd 让 server.py 开机自启、崩溃自动重启
- [ ] 目前手动跑，服务器重启就断

### 公司官网
- [ ] 收集雄楚速通公司信息
- [ ] 制作5页静态网站
- [ ] 部署到 xcstlogistics.com 根域名

---

## 🔑 关键凭证备查

| 项目 | 值 |
|------|-----|
| 服务器 IP | 43.129.175.80 |
| 服务器用户名 | ubuntu |
| 域名 | xcstlogistics.com |
| 企业微信 webhook URL | https://ai.xcstlogistics.com/wecom |
| 公众号 webhook URL | https://ai.xcstlogistics.com/wechat |
| 企业微信 CorpID | wwc870967282b4c3dd |
| AgentID | 1000002 |
| Token | shipment2026 |
| 百炼 API Key | sk-cb668d78ff184cd8bb22fc8378dcbf97 |

---

## 下一个关键里程碑

**明威看到效果**：员工发运单图片 → AI识别 → 数据出来

这一幕发生，后续所有事（备案、V2、月费）都好谈。
