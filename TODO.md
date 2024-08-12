# TODO

- keep an absolute sync schedule in config. we can probably keep it in the status file. the interval will be based on the first successful sync.
- make inital sync optional (flag in config yaml)
- see if we still have the abaility to add a job to the top of the queue while a sync is running
- ability to relaod ALL settings from config file?
- internal python cpu limiter
- no need for "gloabl' keyword because of config ?
- why rdyrun is a parameter in sync instead of unsing config ?
- exclude rule file change shoudl trigger a resync (needs testing)
- dont use these, use a .cahe thing instead
  2024/08/12 12:28:34 NOTICE: - Path2 Queue copy to Path1 - pbs:users/pb-schulz/v/.bisync_status
  2024/08/12 12:28:34 NOTICE: - Path2 Queue copy to Path1 - pbs:users/pb-schulz/v/.resync_status
- status server should be become control server
- allow sync job to top of queue
- sparate filter files per job
- for missing config file we have console output only instead of log file output. maybe fix that
- if an error occured previously, show helpful message how to do a resync with the daemon
- also do the same for non-daemon mode

DONE:
Saw this in a log file. It completed sucessfully but it should have been a resync. It did apparently exit with 0. A manual resync did fix it. Should we implement a resync if we detect that the hash is blank?

```
2024/08/12 21:02:47 NOTICE: WARNING: hash unexpectedly blank despite Fs support (, a6d9b51a142a6d59117f7c77d30c2ca175f1961b) (you may need to --resync!)
2024/08/12 21:02:47 NOTICE: WARNING: hash unexpectedly blank despite Fs support (, a6d9b51a142a6d59117f7c77d30c2ca175f1961b) (you may need to --resync!)
```

```
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Office Pro Plus 2019/OfficeProPlus2019
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Office Pro Plus 2021
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Setup
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Setup/LongPaths for HiDrive
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Starmoney 13
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - Windows 11 Pro
2024/08/12 21:02:47 INFO  : - Path2             File is new                                 - guapdf
2024/08/12 21:02:47 INFO  : Path2:   33 changes:   31 new,    2 modified,    0 deleted
2024/08/12 21:02:47 INFO  : (Modified:    2 newer,    0 older)
2024/08/12 21:02:47 INFO  : Checking access health
2024/08/12 21:02:47 INFO  : Found 1 matching "RCLONE_TEST" files on both paths
2024/08/12 21:02:47 INFO  : Applying changes
2024/08/12 21:02:47 INFO  : Checking potential conflicts...
2024/08/12 21:02:47 NOTICE: Local file system at /home/g/hidrive/Software: 0 differences found
2024/08/12 21:02:47 INFO  : Finished checking the potential conflicts. %!s(<nil>)
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - AppNee.com.Adobe.Acrobat.Pro.DC.v2022.002.FI.UI.UP.for.Win64
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: AppNee.com.Adobe.Acrobat.Pro.DC.v2022.002.FI.UI.UP.for.Win64
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad 2023
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad 2023
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Apps
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Apps
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/Autodesk_AutoCAD_2015_to_2018_Geolocation_Online_Maps_Hotfix_32bit_64bit
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/Autodesk_AutoCAD_2015_to_2018_Geolocation_Online_Maps_Hotfix_32bit_64bit
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/ESRI
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/ESRI
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/ESRI/ArcGISAutoCAD_400
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/ESRI/ArcGISAutoCAD_400
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/ESRI/ArcGISAutoCAD_400/SetupFiles
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/ESRI/ArcGISAutoCAD_400/SetupFiles
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/ESRI/ArcGISAutoCAD_400/SetupFiles/Documentation
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/ESRI/ArcGISAutoCAD_400/SetupFiles/Documentation
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/Scripts
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/Scripts
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/Scripts/Boeschung
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/Scripts/Boeschung
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2018/Scripts/OutlineLWPolyline
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2018/Scripts/OutlineLWPolyline
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2023
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2023
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2023/Autodesk License Patcher V3 for 2021 to 2023
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2023/Autodesk License Patcher V3 for 2021 to 2023
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2023/Autodesk License Patcher V3 for 2021 to 2023/Autodesk License Patcher
2024/08/12 21:02:47 INFO  : This is a directory, not a file. Skipping equality check and will not rename: Autocad Map 2023/Autodesk License Patcher V3 for 2021 to 2023/Autodesk License Patcher
2024/08/12 21:02:47 NOTICE: - WARNING           New or changed in both paths                - Autocad Map 2023/Autodesk License Patcher V3 for 2021 to 2023/Autodesk License Patcher V3 for 2021 to 2023
2024/08/12 21:02:47 INFO  : This is a directory, not a file.
```

```
2024/08/12 21:02:47 INFO  : - Path2             Queue copy to Path1                         - pbs:users/pb-schulz/Software/.bisync_status
2024/08/12 21:02:47 INFO  : - Path2             Queue copy to Path1                         - pbs:users/pb-schulz/Software/.resync_status
2024/08/12 21:02:47 INFO  : - Path2             Do queued copies to                         - Path1
2024/08/12 21:02:47 INFO  : HiDrive root 'users/pb-schulz/Software': Making map for --track-renames
2024/08/12 21:02:47 INFO  : HiDrive root 'users/pb-schulz/Software': Finished making map for --track-renames
2024/08/12 21:02:47 INFO  : .resync_status: Updated modification time in destination
2024/08/12 21:02:48 INFO  : .bisync_status: Updated modification time in destination
2024/08/12 21:02:48 INFO  : There was nothing to transfer
2024/08/12 21:02:48 INFO  : Updating listings
2024/08/12 21:02:48 INFO  : Validating listings for Path1 "pbs:users/pb-schulz/Software/" vs Path2 "/home/g/hidrive/Software/"
2024/08/12 21:02:48 INFO  : Bisync successful
2024/08/12 21:02:48 INFO  :
Transferred:   	          0 B / 0 B, -, 0 B/s, ETA -
Checks:               270 / 270, 100%
Elapsed time:        26.4s

2024-08-12 21:02:48 - INFO - Bisync completed successfully for /home/g/hidrive/Software.
2024-08-12 21:02:48 - INFO - Bisync status for /home/g/hidrive/Software: COMPLETED
```
