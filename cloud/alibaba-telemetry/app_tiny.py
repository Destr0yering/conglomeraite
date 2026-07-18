from flask import Flask,request
import os,time,hmac,hashlib,json,re
app=Flask(__name__)
F=set("schema_version event_id event_type observed_at node_id_hash task_id_hash route role score latency_ms memory_used_fraction degraded stop_reason".split())
R=set("schema_version event_id event_type observed_at node_id_hash".split())
E={"call_completed","route_changed","task_stopped"}
H=re.compile(r"[0-9a-f]{64}")
I=re.compile(r"[A-Za-z0-9._:-]{1,96}")
@app.get("/healthz")
def health():return {"status":"ok"}
@app.post("/",defaults={"path":""})
@app.post("/<path:path>")
def receive(path):
 del path
 b=request.get_data();s=os.getenv("TELEMETRY_HMAC_SECRET","")
 if not 0<len(b)<=8192:return {"message":"bad body"},400
 try:
  t=request.headers["X-ConglomerAIte-Timestamp"]
  x=hmac.new(s.encode(),t.encode()+b"."+b,hashlib.sha256).hexdigest()
  g=request.headers["X-ConglomerAIte-Signature"].removeprefix("sha256=").lower()
  if len(s)<32 or abs(int(time.time())-int(t))>300 or not hmac.compare_digest(g,x):raise ValueError
 except (KeyError,ValueError):return {"message":"invalid signature"},401
 try:
  d=json.loads(b);k=set(d)
  if k-F or R-k or d["schema_version"]!="1.0" or d["event_type"] not in E:raise ValueError
  if not I.fullmatch(d["event_id"]) or not I.fullmatch(d["observed_at"]):raise ValueError
  if not H.fullmatch(d["node_id_hash"]) or ("task_id_hash" in d and not H.fullmatch(d["task_id_hash"])):raise ValueError
  if "score" in d and not 0<=float(d["score"])<=10:raise ValueError
  if "degraded" in d and not isinstance(d["degraded"],bool):raise ValueError
 except (TypeError,ValueError,json.JSONDecodeError):return {"message":"invalid metadata"},400
 print(json.dumps({"log_event":"conglomeraite.telemetry.accepted",**d},separators=(",",":"),sort_keys=True))
 return {"message":"accepted","event_id":d["event_id"]},202
if __name__=="__main__":app.run(host="0.0.0.0",port=9000)
