"""Read-only editor check after rebuilding SaskartaCore with StaffTipBoneLocal."""
import unreal

profile = unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/DA_Traveller_StaffContacts')
assert isinstance(profile, unreal.SaskartaElderWalkProfile)
tip = profile.get_editor_property('StaffTipBoneLocal')
expected = (-0.013812895864248277, 0.0, -0.025146557018160823)
actual = (tip.x, tip.y, tip.z)
assert max(abs(a-b) for a, b in zip(actual, expected)) < 1e-6, actual
print('STAFF_TIP_BONE_LOCAL_VERIFIED', actual,
      'contacts_reviewed=', profile.get_editor_property('bContactsReviewed'))
