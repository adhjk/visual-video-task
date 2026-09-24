# EMOTIV Cortex 后端

该后端统一支持 EPOC X、Insight、EPOC Flex 和 Flex 2，不为不同型号复制采集流程。设备的采样率和通道顺序来自 Cortex 运行时返回值；程序不重采样、不补零、不猜测设备或 Flex 电极布局。

## 前置条件

安装并登录 EMOTIV Launcher，启动 Cortex 服务，注册 Cortex App，并确保许可证允许订阅原始 EEG。凭据只从环境变量读取：

```powershell
$env:EMOTIV_CLIENT_ID = "实际 Client ID"
$env:EMOTIV_CLIENT_SECRET = "实际 Client Secret"
```

不要把凭据写入 YAML 或提交到仓库。首次连接时必须在 EMOTIV Launcher 中批准应用。

## 配置

在所用实验 YAML 中将 `device_type` 改为 `emotiv`，并在现有 `device` 节点下加入：

```yaml
device_type: emotiv
device:
  eeg_startup_timeout_sec: 10.0
  eeg_no_sample_timeout_sec: 5.0
  emotiv:
    model: auto
    headset_id: auto
    client_id_env: EMOTIV_CLIENT_ID
    client_secret_env: EMOTIV_CLIENT_SECRET
    record:
      enabled: true
      title: visual-video-task
    markers:
      enabled: true
    clock_sync:
      enabled: true
    validation:
      expected_sfreq: null
      expected_channels: null
```

`headset_id: auto` 只允许现场发现一台设备；发现多台时程序会列出候选并停止。显式 `model` 与检测结果不一致时也会停止。

正式实验建议填写 `validation.expected_sfreq` 和按 Cortex `subscribe` 返回顺序填写 `expected_channels`。不一致时直接报错，不会自动重采样、删通道或重排通道。

## Flex mapping

Flex 和 Flex 2 必须提供 mapping。将经实验确认的 YAML 放在 `video_eeg/config/emotiv/mappings/<名称>.yaml`，内容直接使用 Cortex `controlDevice.mappings` 格式，然后配置：

```yaml
device:
  emotiv:
    model: epoc_flex
    mapping_profile: visual_32ch
```

mapping 必须包含 `CMS` 和 `DRL`。仓库不附带通用 mapping，因为实际电极与物理 connector 的对应关系属于实验配置，不能由程序猜测。也可用 `mapping_file` 指向明确的绝对或项目相对路径；不能同时设置 `mapping_file` 与 `mapping_profile`。

## 验证边界

本实现依据 Cortex 官方 JSON-RPC、动态 EEG `cols`、headset `settings.eegRate`、`syncWithHeadsetClock` 和 `injectMarker` 契约。自动测试只覆盖解析、验证和缓冲逻辑，不代表四种真实硬件已经通过实验室连接、长时间采集或 marker 时延验收。投入采集前必须逐型号执行短采集、断流、native/local record 对比和 PsychoPy flip-marker 时延测试。
