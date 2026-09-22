# Windows 1.0.4：离线 EEG-BIDS 保存和旧数据导出

正式记录保存后自动生成独立 BIDS 副本；原始 EEG、行为表和续跑进度继续保留。新增开始菜单“视频EEG导出与检查BIDS”，支持旧记录转换与官方全量离线格式校验，无需 Node.js 或联网。

- BrainVision EEG、events.tsv/json、channels.tsv、EEG元数据与数据集信息；按已确认31 EEG通道、µV、IO参考导出。
- 各次退出续跑/采集part分开，不跨空档拼接。完整保留情绪评分、喜好、内容题、疲劳等原行为字段。
- 哈希校验与拒绝覆盖；断流/无可靠事件时间明确标记。格式通过不表示信号质量通过。
- 已有1.0.1–1.0.3：正常保存退出、备份后，复制安装包到本机覆盖安装；不用重拷材料、重新绑定或修改被试进度。沿用1.0.3三条坏片排除。

默认BIDS位置为原数据根sourcedata同级的bids/v1或bids/v2。需要额外约一份EEG磁盘空间。未知设备型号、电极坐标、作者及许可不臆造，官方校验可能仍有推荐信息警告。真实EEG硬件须实验室现场验收。

[主试操作、文件含义和详细故障表](https://github.com/18yiba/visual-video-task/blob/master/docs/operations/BIDS_EXPORT.md)

SHA256SUMS.txt 是安装包字节校验值，核对下载完整性；不用于判断脑电质量。
