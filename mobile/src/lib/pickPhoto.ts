import { Alert } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import type { TFunction } from 'i18next';

import { haptics } from './haptics';
import type { TripDocumentAsset } from './me';

/**
 * Ask for permission, then take a photo or pick one from the gallery.
 * Resolves to null when the driver cancels or refuses permission.
 */
export async function pickPhoto(
  source: 'camera' | 'library',
  t: TFunction,
): Promise<TripDocumentAsset | null> {
  const perm =
    source === 'camera'
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) {
    void haptics.warning();
    Alert.alert(t('tripDocs.permTitle'), t('tripDocs.permBody'));
    return null;
  }

  const options: ImagePicker.ImagePickerOptions = {
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.6,
  };
  const result =
    source === 'camera'
      ? await ImagePicker.launchCameraAsync(options)
      : await ImagePicker.launchImageLibraryAsync(options);
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, mimeType: asset.mimeType, fileName: asset.fileName ?? undefined };
}
