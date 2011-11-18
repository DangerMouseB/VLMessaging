VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLWeakDictionary"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2009 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Private myObjectPtrs As New Dictionary

Property Set item(key As String, anObject As Object)
    If anObject Is Nothing Then
        If myObjectPtrs.exists(key) Then myObjectPtrs.remove key
    Else
        myObjectPtrs(key) = ObjPtr(anObject)
    End If
End Property

Property Get item(key As String) As Object
Attribute item.VB_UserMemId = 0
    Dim tmp As Object
    If Not myObjectPtrs.exists(key) Then Exit Property                      ' return Nothing
    VBoost.AssignAddRef item, CLng(myObjectPtrs(key))
'    apiCopyMemory tmp, myObjectPtrs(key), 4
'    Set item = temp
'    apiCopyMemory temp, 0&, 4
End Property

Property Get ptr(key As String) As Long
    If Not myObjectPtrs.exists(key) Then Exit Property                      ' return 0&
    ptr = myObjectPtrs(key)
End Property

Function keys() As String()
    keys = DBSubArray(myObjectPtrs.keys, , , , , , , vbString, 1)
End Function

Function exists(key As String) As Boolean
    exists = myObjectPtrs.exists(key)
End Function

Function count() As Long
    count = myObjectPtrs.count
End Function

Sub remove(key As String)
    If myObjectPtrs.exists(key) Then myObjectPtrs.remove key        ' don't raise an error like the scripting dictionary
End Sub

Sub removeAll()
    myObjectPtrs.removeAll
End Sub


