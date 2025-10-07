VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMUtils"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = True
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2012 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Function MRHWnd(filename As String, Optional trys As Long = 10) As Long
    Dim i As Long
    MRHWnd = machineRouterHWnd()
    For i = 1 To trys
        If MRHWnd <> 0 Then Exit For
        Call Shell(filename, vbNormalNoFocus)
        MRHWnd = machineRouterHWnd()
    Next
End Function

Function MRClassName() As String
    Dim buffer As String, atomID As Long, length As Long, hWnd As Long
    hWnd = machineRouterHWnd()
    If hWnd = 0 Then Exit Function
    atomID = apiGetPropA(hWnd, "ClassNameAtom")
    If atomID = 0 Then Exit Function
    buffer = Space(255)
    length = apiGlobalGetAtomNameA(atomID, buffer, 255)
    If length = 0 Then Exit Function
    MRClassName = Left$(buffer, length)
End Function

Function MRWindowName() As String
    Dim buffer As String, atomID As Long, length As Long, hWnd As Long
    hWnd = machineRouterHWnd()
    If hWnd = 0 Then Exit Function
    atomID = apiGetPropA(hWnd, "WindowNameAtom")
    If atomID = 0 Then Exit Function
    buffer = Space(255)
    length = apiGlobalGetAtomNameA(atomID, buffer, 255)
    If length = 0 Then Exit Function
    MRWindowName = Left(buffer, length)
End Function

Function BytesAsVariant(buffer() As Byte, indexOfBufferEndPlusOne As Long, indexOfNext As Long) As Variant
    BytesAsVariant = DBBytesAsVariant(buffer, indexOfBufferEndPlusOne, indexOfNext)
End Function

Sub VariantAsBytes(aVariant As Variant, buffer() As Byte, indexOfBufferEndPlusOne As Long, indexOfNext As Long)
    DBVariantAsBytes aVariant, buffer, indexOfBufferEndPlusOne, indexOfNext
End Sub

Function LengthOfVariantAsBytes(aVariant As Variant) As Long
    LengthOfVariantAsBytes = DBLengthOfVariantAsBytes(aVariant)
End Function


