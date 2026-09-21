"use client";
import { useEffect, useState, type FormEvent } from "react";
import { getProfile, updateProfile, type Profile } from "../../../lib/api";
import { writableProfile } from "../../../lib/product";
type Lists = "regions"|"industries"|"capabilities"|"certifications"|"excluded_keywords";
const listFields:[Lists,string][]=[["regions","활동 지역"],["industries","업종"],["capabilities","수행 역량"],["certifications","인증"],["excluded_keywords","제외 키워드"]];
const parse=(value:string)=>value.split(",").map(item=>item.trim()).filter(Boolean);
const staticDemo = process.env.NEXT_PUBLIC_STATIC_DEMO === "true";
export default function ProfilePage(){
  const [profile,setProfile]=useState<Profile|null>(null);
  const [raw,setRaw]=useState<Record<Lists,string>|null>(null);
  const [message,setMessage]=useState("");
  const [saving,setSaving]=useState(false);
  useEffect(()=>{getProfile().then(value=>{setProfile(value);setRaw(Object.fromEntries(listFields.map(([key])=>[key,value[key].join(", ")])) as Record<Lists,string>)}).catch((error:Error)=>setMessage(error.message))},[]);
  if(!profile||!raw)return <main className="state">{message||"기업 프로필을 불러오는 중입니다."}</main>;
  async function save(event:FormEvent){event.preventDefault();setSaving(true);setMessage("");try{const lists=Object.fromEntries(listFields.map(([key])=>[key,parse(raw![key])])) as Pick<Profile,Lists>;const saved=await updateProfile({...writableProfile(profile!),...lists});setProfile(saved);setRaw(Object.fromEntries(listFields.map(([key])=>[key,saved[key].join(", ")])) as Record<Lists,string>);setMessage("프로필을 저장했습니다. 다음 공고 조회부터 반영됩니다.")}catch(error){setMessage((error as Error).message)}finally{setSaving(false)}}
  return <main className="product narrow"><header className="page-head"><div><p className="eyebrow">SYNTHETIC COMPANY</p><h1>기업 프로필</h1><p>{staticDemo
  ? "모든 기업 정보는 합성 데이터입니다. 공개 static demo에서는 지역·인증·금액 eligibility를 브라우저에서 즉시 재계산하고, 관련도 점수는 저장된 시나리오 값을 유지합니다."
  : "모든 기업 정보는 합성 데이터입니다. 저장 후 공고함을 다시 열면 새 조건으로 판단합니다."}</p></div></header><form className="profile-form" onSubmit={save}><label>기업 표시 이름<input required value={profile.display_name} onChange={e=>setProfile({...profile,display_name:e.target.value})}/></label>{listFields.map(([key,label])=><label key={key}>{label}<input value={raw[key]} onChange={e=>setRaw({...raw,[key]:e.target.value})}/><small>쉼표로 구분합니다. 입력 중 쉼표와 공백을 유지합니다.</small></label>)}<div className="form-row"><label>최소 계약 금액<input type="number" min="0" value={profile.min_contract_amount??""} onChange={e=>setProfile({...profile,min_contract_amount:e.target.value||null})}/></label><label>최대 계약 금액<input type="number" min="0" value={profile.max_contract_amount??""} onChange={e=>setProfile({...profile,max_contract_amount:e.target.value||null})}/></label><label>통화<input maxLength={3} value={profile.contract_currency??""} onChange={e=>setProfile({...profile,contract_currency:e.target.value.toUpperCase()||null})}/></label></div><button className="primary" disabled={saving}>{saving?"저장 중…":"변경 저장"}</button><p aria-live="polite">{message}</p></form></main>
}
