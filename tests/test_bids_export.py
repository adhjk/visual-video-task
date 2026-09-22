"""BIDS export tests use synthetic samples and isolated directories only."""
import csv
import json
from pathlib import Path
import numpy as np
import pytest
from video_eeg.utils import bids_export as b


def fixture_record(tmp_path, stamp='20260922_120000', **overrides):
    folder=tmp_path/'source'/'session_01'/stamp; folder.mkdir(parents=True)
    n=3000
    data=np.vstack([np.arange(n),np.arange(31*n).reshape(31,n)/100]).astype('float32')
    np.save(folder/'continuous_eeg.npy',data)
    m=dict(subject_id='TEST01',session_id=1,session_stamp=stamp,sfreq=1000,n_channels=32,device_type='brainco',num_sessions=45,eeg_part=1)
    m.update(overrides);b.write_json(folder/'metadata.json',m)
    events=[dict(name='session_start',sample_index=0,relative_time_sec=0,payload={}),dict(name='EMOTION_VIDEO_ONSET',sample_index=100,relative_time_sec=.1,payload={'trial_id':1,'attempt_id':1,'video_id':'emotion:abc'}),dict(name='EMOTION_VIDEO_OFFSET',sample_index=2100,relative_time_sec=2.1,payload={'trial_id':1,'attempt_id':1,'video_id':'emotion:abc'}),dict(name='VALENCE_RATING_RESPONSE',sample_index=2200,relative_time_sec=2.2,payload={'rating':5,'rt_sec':.1}),dict(name='session_end',sample_index=n,relative_time_sec=3,payload={})]
    b.write_json(folder/'events.json',events)
    return folder,data


def tsv(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))


def test_roundtrip_units_behavior_no_source_change(tmp_path):
    f,data=fixture_record(tmp_path);before={p.name:b.digest(p) for p in f.iterdir()}
    table=f.parent/'emotion_rating_log.csv'
    with table.open('w',encoding='utf-8',newline='') as out:
        w=csv.DictWriter(out,fieldnames=['eeg_recording_dir','eeg_part','trial_id','valence_rating','arousal_rating']);w.writeheader();w.writerow(dict(eeg_recording_dir=str(f),eeg_part=1,trial_id=1,valence_rating=5,arousal_rating=3))
    root=tmp_path/'bids';r=b.export_recording(f,root,protocol='v2')
    import mne
    raw=mne.io.read_raw_brainvision(next(root.rglob('*.vhdr')),preload=True,verbose=False)
    assert raw.ch_names==b.profile_for({'device_type':'brainco'},32)['channel_names']
    assert raw.n_times==3000
    np.testing.assert_allclose(raw.get_data(),data[1:]*1e-6,rtol=1e-7,atol=1e-12)
    rows=tsv(next(root.rglob('*_events.tsv')))
    video=next(r for r in rows if r['trial_type']=='EMOTION_VIDEO_ONSET')
    assert video['onset']=='0.1' and video['duration']=='2'
    summary=next(r for r in rows if r['source_table']=='emotion_rating_log.csv')
    assert summary['valence']=='5' and summary['arousal']=='3'
    assert {p.name:b.digest(p) for p in f.iterdir()}==before
    assert b.export_recording(f,root,protocol='v2')['recordings'][0]['status']=='EXISTS_VERIFIED'
    eeg=next(root.rglob('*.eeg'));eeg.write_bytes(b'corrupt')
    with pytest.raises(b.BidsExportError,match='修改或缺失'):b.export_recording(f,root,protocol='v2')


@pytest.mark.parametrize('overrides,match',[({'device_type':'dummy'},'Demo'),({'local_eeg_recorded':False},'外部'),({'num_sessions':17},'协议'),({'subject_id':'A_B'},'匿名映射'),({'device_type':'unknown'},'设备'),({'sfreq':0},'采样率'),({'sample_count':12},'样本数')])
def test_reject_invalid_metadata(tmp_path,overrides,match):
    f,_=fixture_record(tmp_path,**overrides)
    with pytest.raises(b.BidsExportError,match=match):b.export_recording(f,tmp_path/'bids',protocol='v2')


def test_resumptions_do_not_merge_and_behavior_identity(tmp_path):
    f,_=fixture_record(tmp_path);g,_=fixture_record(tmp_path,'20260922_121000')
    table=f.parent/'emotion_rating_log.csv'
    with table.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=['eeg_recording_dir','eeg_part','trial_id','valence_rating']);w.writeheader()
        for folder,value in [(f,2),(g,7)]:w.writerow(dict(eeg_recording_dir=str(folder),eeg_part=1,trial_id=1,valence_rating=value))
    for folder in (f,g):b.export_recording(folder,tmp_path/'bids',protocol='v2')
    headers=list((tmp_path/'bids').rglob('*.vhdr'));assert len(headers)==2
    ratings=[]
    for path in sorted((tmp_path/'bids').rglob('*_events.tsv')):
        ratings.append(next(r['valence'] for r in tsv(path) if r['source_table']=='emotion_rating_log.csv'))
    assert ratings==['2','7']


def test_freeze_not_fabricated():
    events=[dict(name='video_on',sample_index=1000,relative_time_sec=1,payload={}),dict(name='video_off',sample_index=1000,relative_time_sec=31,payload={})]
    rows,q=b.build_events(events,{},1000,1000)
    assert all(r['onset'] is None and r['duration'] is None and r['eeg_available'] is False for r in rows)
    assert any(r['code']=='SAMPLE_FREEZE' for r in q)


def test_source_changed_no_overwrite(tmp_path):
    f,_=fixture_record(tmp_path);root=tmp_path/'bids';b.export_recording(f,root,protocol='v2')
    eeg=next(root.rglob('*.eeg'));before=b.digest(eeg)
    b.write_json(f/'events.json',[])
    with pytest.raises(b.BidsExportError,match='当前源数据不同'):b.export_recording(f,root,protocol='v2')
    assert b.digest(eeg)==before


def test_unknown_counter_rejected(tmp_path):
    f,data=fixture_record(tmp_path);data[0]=0;np.save(f/'continuous_eeg.npy',data)
    with pytest.raises(b.BidsExportError,match='计数验证'):b.export_recording(f,tmp_path/'bids',protocol='v2')


def test_recovery_csv_refuses_ambiguous_data(tmp_path):
    f,_=fixture_record(tmp_path);(f.parent/'trial_log.recovered_test.csv').write_text('x',encoding='utf-8')
    with pytest.raises(b.BidsExportError,match='恢复CSV'):b.export_recording(f,tmp_path/'bids',protocol='v2')


def test_no_source_nested_output(tmp_path):
    f,_=fixture_record(tmp_path)
    with pytest.raises(b.BidsExportError,match='独立'):b.export_recording(f,f/'bids',protocol='v2')


def test_hook_output_local_config_and_failure_isolation(tmp_path,monkeypatch):
    calls=[]
    def export(d,out,**kw):calls.append(Path(out));raise OSError('disk full')
    monkeypatch.setattr(b,'export_recording',export)
    msg=b.after_recording(tmp_path,{'_unified_protocol':'v2','storage':{'source_data_root':str(tmp_path/'data/sourcedata')}})
    assert '原始数据已保存' in msg and '未完成' in msg
    assert calls==[tmp_path/'data/bids/v2']
    b.after_recording(tmp_path,{'_unified_protocol':'v2','demo_mode':True});assert len(calls)==1


def test_official_validator_offline_all_rows(tmp_path):
    pytest.importorskip('bids_validator_deno');pytest.importorskip('deno')
    f,_=fixture_record(tmp_path);root=tmp_path/'bids';b.export_recording(f,root,protocol='v2')
    report=b.validate_dataset(root)
    assert report['errors']==0
    assert (root/'code/validation_report.json').is_file()


@pytest.mark.parametrize('groups,kinds',[(17,['arithmetic']),(34,['video_mcq']),(17,[])])
def test_historical_protocol_not_relabelled_as_v1(tmp_path,groups,kinds):
    f,_=fixture_record(tmp_path,num_sessions=groups,attention_schedule=[{'task_type':k} for k in kinds])
    with pytest.raises(b.BidsExportError,match='17组内容题'):b.export_recording(f,tmp_path/'bids',protocol='v1')


def test_v1_content_protocol_preserved(tmp_path):
    f,_=fixture_record(tmp_path,num_sessions=17,attention_schedule=[{'task_type':'video_mcq'}])
    r=b.export_recording(f,tmp_path/'bids',protocol='v1')
    assert '_task-videov1_' in r['recordings'][0]['prefix']


def test_multpart_ambiguous_behavior_refused(tmp_path):
    f,_=fixture_record(tmp_path)
    m=b.read_json(f/'metadata.json');m['eeg_part']=2;m['eeg_file']='continuous_eeg_part_002.npy';m['events_file']='events_part_002.json'
    b.write_json(f/'metadata_part_002.json',m)
    (f/'continuous_eeg_part_002.npy').write_bytes((f/'continuous_eeg.npy').read_bytes())
    (f/'events_part_002.json').write_bytes((f/'events.json').read_bytes())
    with (f.parent/'emotion_rating_log.csv').open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=['eeg_recording_dir','trial_id']);w.writeheader();w.writerow({'eeg_recording_dir':str(f),'trial_id':1})
    with pytest.raises(b.BidsExportError,match='缺少eeg_part'):b.export_recording(f,tmp_path/'bids',protocol='v2')
