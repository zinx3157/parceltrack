export const KEY = 'parceltrack.pages.v1';
export const STATUSES = {registered:'Registered',picked_up:'Picked up',in_transit:'In transit',customs:'In customs',out_for_delivery:'Out for delivery',delivered:'Delivered',exception:'Exception',returned:'Returned',cancelled:'Cancelled'};
export const CARRIERS = {dhl:'DHL Express',fedex:'FedEx',aramex:'Aramex',ups:'UPS',colissimo:'Colissimo',dhlecom:'DHL eCommerce',track17:'17TRACK / Postal',manual:'Other / Manual'};
export const CLOSED = ['delivered','returned','cancelled'];
export const now = () => new Date().toISOString();
export const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
export const clean = (value, max=500) => String(value ?? '').trim().slice(0,max);
export const normalize = value => clean(value).replace(/[\s_-]/g,'').toUpperCase();
export const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function emptyData(){return {version:1,company:'ParcelTrack',staleDays:7,parcels:[],clients:[],updatedAt:now()};}
export function dateOnly(value){
  if(!value) return '';
  const s=clean(value,10);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(s) || new Date(s+'T00:00:00Z').toISOString().slice(0,10)!==s) throw new Error('Use a valid date in YYYY-MM-DD format');
  return s;
}
export function positiveInt(value,label='Cartons',max=1000){const n=Number(value);if(!Number.isInteger(n)||n<1||n>max)throw new Error(`${label} must be a whole number between 1 and ${max}`);return n;}
const validIso = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value));
export function validateData(data){
  if(!data || data.version!==1 || !Array.isArray(data.parcels) || !Array.isArray(data.clients))throw new Error('This is not a ParcelTrack backup');
  if(data.parcels.length>20000 || data.clients.length>10000)throw new Error('Backup exceeds the supported workspace size');
  if(typeof data.company!=='string'||data.company.length>120)throw new Error('Invalid company name');
  positiveInt(data.staleDays,'Ageing threshold',365);
  const clientIds=new Set(), parcelIds=new Set(), numbers=new Set();
  for(const c of data.clients){
    if(typeof c.id!=='string'||!c.id||clientIds.has(c.id)||typeof c.name!=='string'||!c.name.trim())throw new Error('Invalid or duplicate client in backup');
    clientIds.add(c.id);
    for(const key of ['name','email','phone','contact','notes'])if(typeof c[key]!=='string'||c[key].length>2000)throw new Error('Invalid client details');
  }
  for(const p of data.parcels){
    if(typeof p.id!=='string'||!p.id||parcelIds.has(p.id)||typeof p.tracking!=='string'||!normalize(p.tracking)||numbers.has(normalize(p.tracking)))throw new Error('Invalid or duplicate parcel in backup');
    parcelIds.add(p.id);numbers.add(normalize(p.tracking));
    if(!Object.hasOwn(STATUSES,p.status)||!Object.hasOwn(CARRIERS,p.carrier))throw new Error('Invalid parcel status or carrier');
    positiveInt(p.cartons);dateOnly(p.eta);
    for(const key of ['tracking','reference','description','origin','destination','notes','clientId','location'])if(typeof p[key]!=='string'||p[key].length>2000)throw new Error('Invalid parcel details');
    if(p.clientId && !clientIds.has(p.clientId))throw new Error('A parcel refers to a missing client');
    if(!validIso(p.createdAt)||!Array.isArray(p.receipts)||!Array.isArray(p.events))throw new Error('Invalid parcel history');
    if(p.receipts.length>p.cartons || p.events.length>10000)throw new Error('Invalid carton count or oversized timeline');
    for(const rec of p.receipts)if(!validIso(rec.at)||typeof rec.location!=='string'||typeof rec.by!=='string')throw new Error('Invalid receipt');
    for(const e of p.events)if(!validIso(e.at)||typeof e.text!=='string'||e.text.length>2000||!['manual','warehouse'].includes(e.source))throw new Error('Invalid event');
    if(p.release && (!validIso(p.release.at)||typeof p.release.to!=='string'||!p.release.to.trim()||p.receipts.length!==p.cartons))throw new Error('Invalid release');
  }
  return data;
}
export class Workspace {
  constructor(storage){
    this.storage=storage;this.raw=storage.getItem(KEY);
    try {this.data=this.raw?validateData(JSON.parse(this.raw)):emptyData();}
    catch {throw new Error('Saved records could not be read. They have been preserved. Download the saved data from the recovery screen.');}
    const probe=KEY+'.probe';storage.setItem(probe,'1');storage.removeItem(probe);
  }
  change(fn){
    if(this.storage.getItem(KEY)!==this.raw)throw new Error('Records changed in another tab. Reload before saving.');
    const next=JSON.parse(JSON.stringify(this.data));const result=fn(next);next.updatedAt=now();validateData(next);
    const encoded=JSON.stringify(next);
    try {this.storage.setItem(KEY,encoded);}catch{throw new Error('Could not save. Browser storage may be full or blocked. Export a backup and free space before retrying.');}
    this.raw=encoded;this.data=next;return result;
  }
  parcel(id){const p=this.data.parcels.find(p=>p.id===id);if(!p)throw new Error('Parcel not found');return p;}
  addParcel(input){let id;this.change(d=>{const p=makeParcel(input,d);d.parcels.unshift(p);id=p.id;});return id;}
  updateParcel(id,input){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p)throw new Error('Parcel not found');
    const next=makeParcel({...p,...input},d,id);
    if(next.cartons<p.receipts.length)throw new Error('Expected cartons cannot be lower than the received count');
    if(p.release&&next.cartons!==p.cartons)throw new Error('Undo release before changing the carton count');
    Object.assign(p,next,{id:p.id,createdAt:p.createdAt,receipts:p.receipts,release:p.release,events:p.events});
    p.events.unshift({at:now(),text:'Parcel details updated',source:'manual'});
  });}
  addClient(input,id=''){let result;this.change(d=>{const name=clean(input.name,120);if(!name)throw new Error('Enter a client name');
    if(d.clients.some(c=>c.id!==id&&c.name.toLowerCase()===name.toLowerCase()))throw new Error('A client with this name already exists');
    const c={id:id||uid(),name,email:clean(input.email,200),phone:clean(input.phone,100),contact:clean(input.contact,120),notes:clean(input.notes,1000)};
    if(id){const index=d.clients.findIndex(c=>c.id===id);if(index<0)throw new Error('Client not found');d.clients[index]=c;}else d.clients.push(c);result=c.id;
  });return result;}
  addEvent(id,{status,text,at}){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p)throw new Error('Parcel not found');if(!Object.hasOwn(STATUSES,status))throw new Error('Choose a valid status');
    const time=at?new Date(at).toISOString():now();if(Date.parse(time)>Date.now()+60000)throw new Error('Updates cannot be dated in the future');
    const message=clean(text,1000);if(!message)throw new Error('Describe the update');
    p.events.unshift({at:time,status,text:message,source:'manual'});p.events.sort((a,b)=>Date.parse(b.at)-Date.parse(a.at));
    const latest=p.events.find(e=>e.source==='manual'&&e.status);p.status=latest?.status||status;
  });}
  lookup(code){const n=normalize(code);if(!n)return null;const exact=this.data.parcels.filter(p=>normalize(p.tracking)===n);if(exact.length===1)return exact[0];
    const matches=this.data.parcels.filter(p=>normalize(p.tracking).includes(n));if(matches.length>1)throw new Error('Several parcels match. Scan or enter the full tracking number.');return matches[0]||null;}
  receive(id,{count=1,location='',by=''}){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p)throw new Error('Parcel not found');if(p.release)throw new Error('Undo the release before receiving');
    count=positiveInt(count);if(p.receipts.length+count>p.cartons)throw new Error('Receipt exceeds the expected carton count. Check the parcel details.');
    const timestamp=now();for(let i=0;i<count;i++)p.receipts.push({at:timestamp,location:clean(location,120),by:clean(by,120)});
    if(location)p.location=clean(location,120);p.events.unshift({at:timestamp,text:`Received ${count} carton(s) — ${p.receipts.length}/${p.cartons} total${p.location?' · '+p.location:''}`,source:'warehouse'});
  });}
  release(id,to){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p)throw new Error('Parcel not found');if(p.release)throw new Error('This parcel is already released');if(p.receipts.length!==p.cartons)throw new Error('Receive all expected cartons before release');
    const recipient=clean(to,200);if(!recipient)throw new Error('Enter the person or company receiving the goods');
    p.release={at:now(),to:recipient};p.events.unshift({at:p.release.at,text:'Released to '+recipient,source:'warehouse'});
  });}
  undoRelease(id){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p?.release)throw new Error('This parcel has no release to undo');p.release=null;p.events.unshift({at:now(),text:'Release cancelled — back in warehouse',source:'warehouse'});});}
  undoReceipt(id){this.change(d=>{const p=d.parcels.find(p=>p.id===id);if(!p?.receipts.length)throw new Error('No receipts to clear');if(p.release)throw new Error('Undo the release first');p.receipts=[];p.location='';p.events.unshift({at:now(),text:'Warehouse receipt cleared',source:'warehouse'});});}
  importRows(rows){let added=0;this.change(d=>{if(!rows.length)throw new Error('No parcels found');for(const row of rows){if(d.parcels.some(p=>normalize(p.tracking)===normalize(row.tracking)))continue;d.parcels.unshift(makeParcel(row,d));added++;}});return added;}
  restore(data){validateData(data);this.change(d=>Object.assign(d,JSON.parse(JSON.stringify(data))));}
}
export function makeParcel(input,data,existingId=''){
  const tracking=clean(input.tracking,100);if(!normalize(tracking))throw new Error('Enter a tracking number');
  if(data.parcels.some(p=>p.id!==existingId&&normalize(p.tracking)===normalize(tracking)))throw new Error('This tracking number already exists');
  const carrier=input.carrier||'manual',status=input.status||'registered';if(!Object.hasOwn(CARRIERS,carrier)||!Object.hasOwn(STATUSES,status))throw new Error('Invalid carrier or status');
  const clientId=input.clientId||'';if(clientId&&!data.clients.some(c=>c.id===clientId))throw new Error('Choose an existing client');
  return {id:existingId||uid(),tracking,carrier,status,clientId,reference:clean(input.reference,120),description:clean(input.description,500),origin:clean(input.origin,120),destination:clean(input.destination,120),notes:clean(input.notes,1000),location:clean(input.location,120),eta:dateOnly(input.eta),cartons:positiveInt(input.cartons===''||input.cartons==null?1:input.cartons),createdAt:now(),receipts:[],release:null,events:[{at:now(),status,text:'Parcel registered',source:'manual'}]};
}
export function shelfDays(p,time=Date.now()){return p.receipts.length?Math.max(0,Math.floor((time-Date.parse(p.receipts[0].at))/86400000)):0;}
export function carrierURL(p){const n=encodeURIComponent(p.tracking);return ({dhl:`https://www.dhl.com/global-en/home/tracking.html?tracking-id=${n}`,fedex:`https://www.fedex.com/fedextrack/?trknbr=${n}`,ups:`https://www.ups.com/track?tracknum=${n}`,aramex:`https://www.aramex.com/track/results?ShipmentNumber=${n}`,colissimo:`https://www.laposte.fr/outils/suivre-vos-envois?code=${n}`,dhlecom:`https://www.dhl.com/global-en/home/tracking.html?tracking-id=${n}`,track17:`https://t.17track.net/en#nums=${n}`})[p.carrier]||'';}
export function parseCSV(text){
  text=String(text).replace(/^\uFEFF/,'');const rows=[];let row=[],field='',quoted=false;
  const delimiter=(text.split(/\r?\n/)[0].match(/;/g)||[]).length>(text.split(/\r?\n/)[0].match(/,/g)||[]).length?';':',';
  for(let i=0;i<text.length;i++){const ch=text[i];if(ch==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else if(quoted||!field)quoted=!quoted;else field+=ch;}else if(ch===delimiter&&!quoted){row.push(field);field='';}else if((ch==='\n'||ch==='\r')&&!quoted){if(ch==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(x=>x.trim()))rows.push(row);row=[];field='';}else field+=ch;}
  if(quoted)throw new Error('CSV contains an unclosed quoted field');row.push(field);if(row.some(x=>x.trim()))rows.push(row);if(!rows.length)return [];
  const aliases={tracking:'tracking',tracking_number:'tracking',awb:'tracking',numero_suivi:'tracking',carrier:'carrier',transporteur:'carrier',reference:'reference',client_reference:'reference',description:'description',origin:'origin',destination:'destination',cartons:'cartons',cartons_expected:'cartons',eta:'eta',status:'status',notes:'notes',location:'location',storage_location:'location'};
  const headers=rows.shift().map(x=>aliases[x.trim().toLowerCase().replace(/[\s-]+/g,'_')]||'');if(!headers.includes('tracking'))throw new Error('CSV needs a tracking_number column');
  return rows.map((r,index)=>{const obj={};headers.forEach((h,i)=>{if(h)obj[h]=r[i]||'';});if(!obj.tracking)throw new Error(`Missing tracking number on CSV row ${index+2}`);return obj;});
}
export function csvExport(parcels,clients=[]){const columns=['tracking_number','carrier','status','client','reference','description','origin','destination','cartons_expected','cartons_received','storage_location','eta','released_to'];
  const safe=v=>{let s=String(v??'');if(/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
  const lines=parcels.map(p=>[p.tracking,p.carrier,p.status,clients.find(c=>c.id===p.clientId)?.name||'',p.reference,p.description,p.origin,p.destination,p.cartons,p.receipts.length,p.location,p.eta,p.release?.to||'']);return '\uFEFF'+[columns,...lines].map(r=>r.map(safe).join(',')).join('\r\n');}
