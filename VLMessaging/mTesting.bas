Attribute VB_Name = "mTesting"
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2011 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Sub test1()
    Dim fred As New Dictionary
    Debug.Print fred("hello")               ' the naughty thing adds an Empty at key "hello" !!!!!
    fred.remove "hello"
    Debug.Print fred.CompareMode
    fred.remove "hello"                     ' so this remove raises an error!!!!
End Sub

Sub test2()
    Dim fred As New VLMWeakDictionary, a As New Collection, b As Collection
    InitVBoost
    a.Add 1
    Set fred("a") = a
    Set b = fred("a")
End Sub

Sub exampleFindVLMMR()
    Dim hVLMMR As Long, utils As New VLMUtils
    hVLMMR = utils.MRHWnd("VLMMR.exe")
    If hVLMMR = 0 Then Debug.Print "Couldn't find router": Exit Sub
    Debug.Print "ClassName: " & utils.MRClassName()
    Debug.Print "WindowName: " & utils.MRWindowName()
End Sub


