# 公司数字员工工作台管理台

首个页面为“知识权限管理”，用于超级管理员按岗位或数字员工配置企业知识库访问范围。

## 本地运行

```powershell
npm install
npm run dev
```

默认开发地址由 Vite 输出（通常为 `http://localhost:5173`）。

## API 配置

- `VITE_API_BASE_URL`：工作台服务地址，默认 `http://localhost:8000/api/v1`
- `VITE_TENANT_ID`、`VITE_USER_ID`、`VITE_USER_ROLE`：开发环境身份标识

开发环境使用请求头模拟身份。生产环境必须替换为统一登录、短期会话和设备绑定，客户端提供的角色不能作为安全依据。

## 检查

```powershell
npm test -- --run
npm run build
```

页面只通过服务端 API 访问权限数据，不直接连接数据库，也不会保存密码、Cookie、验证码或原始密钥。
