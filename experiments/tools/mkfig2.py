#!/usr/bin/env python3
"""Regenerate all three Chapter 6 figures for Unit loss / Reconstitution.

Usage:  python3 make_figures.py [TRACE_LOG] [OUTDIR]
Defaults: campaign_unitloss_4.log  ->  chapters/ch6/assets/
"""
import sys, os, datetime as dt
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, matplotlib.dates as mdates

TRACE = sys.argv[1] if len(sys.argv) > 1 else 'campaign_unitloss_4.log'
OUT   = sys.argv[2] if len(sys.argv) > 2 else 'chapters/ch6/assets'
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({'font.family':'serif','font.size':9,'axes.labelsize':9,
 'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,
 'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150,
 'axes.grid':True,'grid.alpha':0.25,'grid.linewidth':0.5})
GREY='#4d4d4d'; ACC='#8c2d19'; LT='#9099a2'
D = lambda *a: dt.datetime(2026,8,9,*a)

rows=[]
for line in open(TRACE):
    p=line.split()
    if len(p)!=4 or not p[0].startswith('2026') or '===' in line: continue
    t=dt.datetime.strptime(p[0],'%Y-%m-%dT%H:%M:%SZ')
    hs={k:int(v) for k,v in (kv.split('=') for kv in p[1].split(','))}
    rows.append((t,hs,int(p[2]),int(p[3])))
print(f'{len(rows)} samples, {rows[0][0]} -> {rows[-1][0]}')

# ---------------------------------------------------------------- FIGURE 1
# Block interval by phase. Values are measured over full phase windows;
# P3 has no interval to plot (chain halted) and is drawn hatched.
ph=[('Baseline\n4 of 4',2.00,GREY),('P1\n3 of 4',3.33,ACC),
    ('P2 stable\n5 of 5',1.99,GREY),('P2b\n4 of 5',3.02,ACC),
    ('P3\n3 of 5',None,'#1f1f1f')]
fig,ax=plt.subplots(figsize=(6.2,2.9))
for i,(lab,v,c) in enumerate(ph):
    if v is None:
        ax.bar(i,4.2,color='none',edgecolor='#1f1f1f',hatch='///',linewidth=0.8)
        ax.text(i,4.35,'halted',ha='center',va='bottom',fontsize=8,style='italic')
    else:
        ax.bar(i,v,color=c,width=0.62)
        ax.text(i,v+0.08,f'{v:.2f}',ha='center',va='bottom',fontsize=8)
for base,lo,hi,txt in [(2.00,0,1,'+67%'),(1.99,2,3,'+52%')]:
    ax.annotate('',xy=(hi,ph[hi][1]),xytext=(lo,base),
                arrowprops=dict(arrowstyle='-|>',color=ACC,lw=0.8,shrinkA=2,shrinkB=2))
    ax.text((lo+hi)/2,(base+ph[hi][1])/2+0.28,txt,ha='center',fontsize=8,color=ACC)
ax.set_xticks(range(len(ph))); ax.set_xticklabels([p[0] for p in ph])
ax.set_ylabel('L1 block interval (s)'); ax.set_ylim(0,5.0)
ax.axhline(2.00,color=LT,lw=0.7,ls=':',zorder=0)
fig.tight_layout(); fig.savefig(f'{OUT}/fig_unitloss_interval.pdf'); plt.close(fig)

# ---------------------------------------------------------------- FIGURE 2
# Campaign timeline. Chain height is plotted as a single line because all
# reachable validators agree; absences are shown by the step panel rather
# than by per-validator traces, which would draw a misleading flat segment
# across each outage.
sub=[r for r in rows if r[0]<=D(16,35)]; t=[r[0] for r in sub]
fig,(a1,a2,a3)=plt.subplots(3,1,figsize=(6.6,5.2),sharex=True,
    gridspec_kw={'height_ratios':[1.3,0.5,1.1],'hspace':0.18})
a1.plot(t,[max(r[1].values()) for r in sub],lw=1.3,color=GREY)
a1.set_ylabel('L1 height')
a2.step(t,[len(r[1]) for r in sub],where='post',lw=1.2,color=GREY)
a2.set_ylabel('Validators\nreachable'); a2.set_yticks([3,4]); a2.set_ylim(2.6,4.4)
a3.plot(t,[r[2] for r in sub],lw=1.2,color=GREY,label='L2 produced')
a3.plot(t,[r[3] for r in sub],lw=1.2,color=ACC,label='L2 settled')
a3.set_ylabel('L2 block'); a3.legend(frameon=False,loc='upper left')
bands=[(D(14,49,26),D(15,13,16),'one unit absent  3 of 4'),
       (D(16,8,29), D(16,16,32),'below quorum  3 of 5')]
for ax in (a1,a2,a3):
    for x0,x1,_ in bands: ax.axvspan(x0,x1,color=ACC,alpha=0.10,lw=0)
for x0,x1,lab in bands:
    a1.text(x0+(x1-x0)/2,1.02,lab,transform=a1.get_xaxis_transform(),
            ha='center',va='bottom',fontsize=7.5,color=ACC)
a1.annotate('2.00 s/block',xy=(D(14,42),250850),xytext=(D(14,33),251450),
            fontsize=7.5,color=GREY,arrowprops=dict(arrowstyle='-',color=LT,lw=0.6))
a1.annotate('3.33 s/block',xy=(D(14,58),250980),xytext=(D(15,6),250480),
            fontsize=7.5,color=ACC,arrowprops=dict(arrowstyle='-',color=ACC,lw=0.6))
a1.annotate('halted 483 s',xy=(D(16,12),252373),xytext=(D(15,40),252560),
            fontsize=7.5,color=ACC,arrowprops=dict(arrowstyle='-|>',color=ACC,lw=0.7))
a3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M')); a3.set_xlabel('Time (UTC)')
fig.subplots_adjust(top=0.90,left=0.13,right=0.98,bottom=0.10)
fig.savefig(f'{OUT}/fig_unitloss_timeline.pdf'); plt.close(fig)

# ---------------------------------------------------------------- FIGURE 3
# Produced vs settled across the full observation, including the 4.5 h in
# which settlement never advanced.
fig,ax=plt.subplots(figsize=(6.4,3.0))
t=[r[0] for r in rows]
prod=[r[2] for r in rows]; sett=[r[3] for r in rows]
ax.plot(t,prod,lw=1.3,color=GREY,label='L2 blocks produced')
ax.plot(t,sett,lw=1.3,color=ACC,label='L2 blocks settled')
gap=prod[-1]-sett[-1]
ax.axvline(D(16,16,32),color='#1f1f1f',lw=0.8,ls='--')
ax.text(D(16,25),52350,'consensus recovers 16:16:32',fontsize=7.5)
ax.annotate('final settlement advance 16:16:45',xy=(D(16,16,45),49556),
            xytext=(D(17,5),48950),fontsize=7.5,color=ACC,
            arrowprops=dict(arrowstyle='-|>',color=ACC,lw=0.7))
ax.annotate('',xy=(D(20,40),prod[-1]),xytext=(D(20,40),sett[-1]),
            arrowprops=dict(arrowstyle='<|-|>',color=LT,lw=0.8))
ax.text(D(20,28),51100,f'unanchored\nwindow\n{gap} blocks',
        fontsize=7.5,ha='right',color=GREY)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax.set_xlabel('Time (UTC)'); ax.set_ylabel('L2 block number')
ax.set_ylim(48800,52800); ax.legend(frameon=False,loc='upper left')
fig.tight_layout(); fig.savefig(f'{OUT}/fig_reconstitution_divergence.pdf'); plt.close(fig)

print(f'wrote 3 figures to {OUT}/  (unanchored window at end: {gap} blocks)')
