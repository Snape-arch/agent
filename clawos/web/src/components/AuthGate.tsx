import { useEffect, useState, type ReactNode } from 'react';
import { bootstrapOwner, fetchCurrentUser, login, logout, type CurrentUser } from '../api';

export function AuthGate({children}:{children:(user:CurrentUser)=>ReactNode}){
  const [user,setUser]=useState<CurrentUser>();const [ready,setReady]=useState(false);const [setup,setSetup]=useState(false);
  const [email,setEmail]=useState('');const [password,setPassword]=useState('');const [tenant,setTenant]=useState('ClawVision');const [error,setError]=useState('');
  useEffect(()=>{fetchCurrentUser().then(setUser).catch(()=>{}).finally(()=>setReady(true));},[]);
  async function submit(){setError('');try{const response=setup?await bootstrapOwner(email,password,tenant):await login(email,password);setUser({userId:response.data.userId,tenantId:response.data.tenantId,role:response.data.role as CurrentUser['role'],scopes:['*']});}catch(reason){setError(reason instanceof Error?reason.message:'认证失败');}}
  if(!ready)return <main className="auth-shell"><div className="auth-card">正在验证工作区…</div></main>;
  if(!user)return <main className="auth-shell"><form className="auth-card" onSubmit={event=>{event.preventDefault();void submit();}}><div className="auth-brand">CLAWVISION · 0.17</div><h1>{setup?'初始化安全工作区':'登录实验工作区'}</h1><p>账户、实验、数据与模型资产按租户隔离。</p>{setup&&<label>工作区名称<input value={tenant} onChange={e=>setTenant(e.target.value)} required/></label>}<label>邮箱<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required/></label><label>密码<input type="password" minLength={12} value={password} onChange={e=>setPassword(e.target.value)} required/></label>{error&&<div className="auth-error">{error}</div>}<button className="run-button" type="submit">{setup?'创建 Owner':'登录'}</button><button className="auth-switch" type="button" onClick={()=>{setSetup(!setup);setError('');}}>{setup?'已有工作区，返回登录':'首次安装？初始化 Owner'}</button></form></main>;
  return <><aside className="session-strip" aria-label="当前会话"><span>{user.role} · {user.tenantId}</span><button onClick={logout}>退出</button></aside>{children(user)}</>;
}
