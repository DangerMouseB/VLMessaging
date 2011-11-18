Attribute VB_Name = "mTesting"
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2009 - All rights reserved
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
    Dim fred As New VLWeakDictionary, a As New Collection, b As Collection
    InitVBoost
    a.Add 1
    Set fred("a") = a
    Set b = fred("a")
End Sub
