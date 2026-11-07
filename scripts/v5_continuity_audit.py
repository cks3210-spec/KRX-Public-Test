#!/usr/bin/env python3
"""Audit the persistent v5 ledger without modifying existing v4/GC or research grades."""
import csv,json,pathlib,datetime,collections
P=pathlib.Path("data/v5_integrated")
O=pathlib.Path("v5_continuity_out");O.mkdir(exist_ok=True)
def read(name):
 p=P/name
 if not p.exists():return []
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
prices=read("daily_prices.csv")
episodes=read("episodes.csv")
oldperf=read("performance.csv")
status={"mode":"CONTINUITY_AUDIT_ONLY","daily_formal_rescoring":"NOT_IMPLEMENTED","final_buy_signals":0,
        "market_days_confirmed":[],"market_days_unverified":[],"safe_performance_completed":0,
        "safe_performance_pending":0,"safe_performance_blocked":0}
try:
 if not prices:raise RuntimeError("No persistent daily_prices.csv")
 if not episodes:raise RuntimeError("No persistent episodes.csv")
 byday=collections.defaultdict(lambda:collections.defaultdict(dict))
 for r in prices:
  d=r["date"];m=r["market"];c=r["code"];p=float(r["close"])
  if m not in ("KOSPI","KOSDAQ") or p<=0:raise ValueError("Invalid market/price")
  if c in byday[d][m]:raise ValueError("Duplicate market/date/code "+d+" "+c)
  byday[d][m][c]=p
 dates=sorted(byday)
 status["observed_dates"]=dates
 # Each observed date must contain both markets with enough securities.
 for d in dates:
  counts={m:len(byday[d].get(m,{})) for m in ("KOSPI","KOSDAQ")}
  if counts["KOSPI"]<500 or counts["KOSDAQ"]<1000:
   status["market_days_unverified"].append({"date":d,"counts":counts})
  else:status["market_days_confirmed"].append(d)
 verified=status["market_days_confirmed"]
 # A missing weekday could be a holiday. Do not pretend to know: flag for official KRX calendar verification.
 gaps=[]
 for a,b in zip(verified,verified[1:]):
  da=datetime.datetime.strptime(a,"%Y%m%d").date()
  db=datetime.datetime.strptime(b,"%Y%m%d").date()
  possible=[]
  t=da+datetime.timedelta(days=1)
  while t<db:
   if t.weekday()<5:possible.append(t.strftime("%Y%m%d"))
   t+=datetime.timedelta(days=1)
  if possible:gaps.append({"after":a,"before":b,"unverified_weekdays":possible,
                           "resolution":"KRX_HOLIDAY_OR_MISSING_SNAPSHOT_NOT_YET_VERIFIED"})
 status["possible_gaps"]=gaps
 # Conservative: until an authoritative trading calendar confirms holidays, do not mark a
 # 5/10/20-session outcome DONE if an unverified weekday is between entry and target.
 results=[]
 for e in episodes:
  entry=e["entry_date"];market=e["market"];code=e["code"];eid=e["episode_id"]
  start=float(e["entry_price"])
  if start<=0:raise ValueError("Invalid episode entry price")
  later=[d for d in verified if d>entry]
  for h in (5,10,20):
   target=later[h-1] if len(later)>=h else ""
   uncertain=[]
   if target:
    a=datetime.datetime.strptime(entry,"%Y%m%d").date()
    b=datetime.datetime.strptime(target,"%Y%m%d").date()
    t=a+datetime.timedelta(days=1)
    known=set(verified)
    while t<=b:
     k=t.strftime("%Y%m%d")
     if t.weekday()<5 and k not in known:uncertain.append(k)
     t+=datetime.timedelta(days=1)
   price=byday.get(target,{}).get(market,{}).get(code) if target else None
   result=("PENDING" if not target else
           "CALENDAR_UNVERIFIED" if uncertain else
           "PRICE_MISSING" if price is None else "DONE")
   row={"episode_id":eid,"entry_date":entry,"market":market,"code":code,
        "horizon":h,"target_date":target,"target_close":price if result=="DONE" else "",
        "return_pct":round((price/start-1)*100,4) if result=="DONE" else "",
        "result":result,"unverified_weekdays":";".join(uncertain)}
   results.append(row)
 for r in results:
  if r["result"]=="DONE":status["safe_performance_completed"]+=1
  elif r["result"]=="PENDING":status["safe_performance_pending"]+=1
  else:status["safe_performance_blocked"]+=1
 with (O/"audited_performance.csv").open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(results[0]) if results else
   ["episode_id","entry_date","market","code","horizon","target_date","target_close","return_pct","result","unverified_weekdays"])
  w.writeheader();w.writerows(results)
 status.update(episodes=len(episodes),performance_rows=len(results),archived_price_rows=len(prices),
               observed_market_dates=len(dates),status="AUDIT_COMPLETED",
               notes="Potential weekday gaps must be checked against official KRX holidays before accepting completed returns.")
except Exception as ex:
 status.update(status="AUDIT_FAILED",error=str(ex))
 raise
finally:
 (O/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
