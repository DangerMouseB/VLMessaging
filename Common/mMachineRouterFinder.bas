Attribute VB_Name = "mMachineRouterFinder"
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2012 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Private myHWnd As Long

Function machineRouterHWnd() As Long
    myHWnd = 0
    apiEnumWindows AddressOf EnumWindowsProc, 0
    machineRouterHWnd = myHWnd
End Function

Private Function EnumWindowsProc(ByVal hWnd As Long, ByVal lparam As Long) As Long
    If apiGetPropA(hWnd, "IsVLMMachineRouter") = 1 Then
        EnumWindowsProc = 0
        myHWnd = hWnd
    Else
        EnumWindowsProc = 1
    End If
End Function

